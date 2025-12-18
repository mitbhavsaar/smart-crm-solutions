# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class CrmMaterialLine(models.Model):
    _inherit = "crm.material.line"

    product_config_mode = fields.Selection(
        related='product_template_id.product_config_mode',
        depends=['product_template_id'],
        help="Product configuration mode"
    )

    product_custom_attribute_value_ids = fields.One2many(
        comodel_name='product.attribute.custom.value',
        inverse_name='crm_order_line_id',
        string="Custom Values",
        compute='_compute_custom_attribute_values',
        help="Product custom attribute values",
        store=True,
        readonly=False,
        precompute=True,
        copy=True
    )
    
    attributes_description = fields.Text(
        string=" Description",
        compute="_compute_attributes_description",
        store=True
    )

    attributes_json = fields.Json(
        string="Attribute Map",
        compute="_compute_attributes_json",
        store=True
    )
    
    # NEW: BOQ Attachment fields (was conditional file)
    boq_attachment_id = fields.Binary(
        string="BOQ Attachment",
        attachment=True,
        help="File uploaded based on attribute value selection"
    )
    boq_attachment_name = fields.Char(
        string="BOQ Attachment Name"
    )
    requires_conditional_file = fields.Boolean(
        string="Requires File Upload",
        compute="_compute_requires_conditional_file",
        store=True,
        help="True if any selected attribute value has 'Required File?' enabled"
    )
    
    @api.depends('product_template_attribute_value_ids')
    def _compute_requires_conditional_file(self):
        """Check if any selected attribute value requires a file upload"""
        for record in self:
            requires_file = False
            for ptav in record.product_template_attribute_value_ids:
                # Only check for radio/select display types
                if ptav.attribute_id.display_type in ['radio', 'select'] and ptav.required_file:
                    requires_file = True
                    break
            record.requires_conditional_file = requires_file
    
    @api.constrains('product_template_attribute_value_ids', 'boq_attachment_id')
    def _check_conditional_file_required(self):
        """Validate that file is attached when required"""
        for record in self:
            if record.requires_conditional_file and not record.boq_attachment_id:
                # Find which attribute requires the file
                required_attrs = []
                for ptav in record.product_template_attribute_value_ids:
                    if ptav.attribute_id.display_type in ['radio', 'select'] and ptav.required_file:
                        required_attrs.append(f"{ptav.attribute_id.name}: {ptav.name}")
                
                if required_attrs:
                    raise ValidationError(
                        f"File upload is required for the following selection(s):\n" +
                        "\n".join(f"• {attr}" for attr in required_attrs)
                    )

    
    
    @api.depends(
        'product_template_attribute_value_ids',
        'product_custom_attribute_value_ids',
        'attached_file_name'
    )
    def _compute_attributes_description(self):
        """Attributes description WITHOUT file upload and WITHOUT Quantity UOM"""
        for record in self:
            template_attrs = []

            # Collect selected attributes for dependency checks
            selected_attributes = {}
            for ptav in record.product_template_attribute_value_ids:
                if ptav.attribute_id:
                    selected_attributes[ptav.attribute_id.name] = ptav.name

            # Dependency: Gel Coat REQ/Required == yes → then show Gel-coat
            # Check both "Gel Coat REQ" and "Gel Coat Required" for compatibility
            gel_coat_req_value = (
                selected_attributes.get("Gel Coat REQ", "") or 
                selected_attributes.get("Gel Coat Required", "")
            ).lower()
            # Skip Gel-coat if value is "no" or empty
            skip_gel_coat = gel_coat_req_value not in ["yes", "true", "1", "required"]

            for ptav in record.product_template_attribute_value_ids:
                attr = ptav.attribute_id
                if not attr:
                    continue

                key = attr.name
                display_type = attr.display_type

                # 🚫 SKIP file upload attributes
                if display_type == "file_upload":
                    continue

                # 🚫 SKIP attributes flagged as is_quantity
                if attr.is_quantity:
                    continue

                # 🚫 SKIP Quantity UOM completely (case insensitive)
                if key.strip().lower() == "quantity uom":
                    continue

                # 🚫 SKIP Gel-coat only when Gel Coat Required != true/yes/1
                if skip_gel_coat and key.lower() in ["gel-coat", "gel coat"]:
                    continue

                # 🔥 M2O attributes → only add if user selected a record AND has value
                if display_type == "m2o":
                    if ptav.m2o_res_id and ptav.name and ptav.name.strip():
                        rec = self.env[attr.m2o_model_id.model].sudo().browse(ptav.m2o_res_id)
                        value = rec.display_name if rec else ptav.name
                        if value and value.strip():
                            template_attrs.append(f"{key}: {value}")
                else:
                    # Regular attributes (non-M2O)
                    value = ptav.name
                    if value and value.strip():
                        template_attrs.append(f"{key}: {value}")

            # Custom attribute values
            custom_attrs = []
            for custom in record.product_custom_attribute_value_ids:
                ptav = custom.custom_product_template_attribute_value_id
                if ptav and ptav.attribute_id and custom.custom_value and custom.custom_value.strip():
                    custom_attrs.append(f"{ptav.attribute_id.name}: {custom.custom_value}")

            # Final description
            record.attributes_description = ", ".join(template_attrs + custom_attrs) if (template_attrs or custom_attrs) else ""

            
    @api.depends(
        'attached_file_id',
        'attached_file_name',
        'product_template_attribute_value_ids',
        'product_custom_attribute_value_ids',
    )
    def _compute_attributes_json(self):
        """Attributes JSON WITHOUT file upload and conditional Gel-coat"""
        for record in self:
            data = {}
            
            try:
                # Collect selected attributes for dependency checks
                selected_attributes = {}
                for ptav in record.product_template_attribute_value_ids:
                    if ptav.attribute_id:
                        selected_attributes[ptav.attribute_id.name] = ptav.name

                # Dependency: Gel Coat REQ/Required == yes → then show Gel-coat
                # Check both "Gel Coat REQ" and "Gel Coat Required" for compatibility
                gel_coat_req_value = (
                    selected_attributes.get("Gel Coat REQ", "") or 
                    selected_attributes.get("Gel Coat Required", "")
                ).lower()
                # Skip Gel-coat if value is "no" or empty
                skip_gel_coat = gel_coat_req_value not in ["yes", "true", "1", "required"]

                # Template attributes (SKIP file_upload)
                for ptav in record.product_template_attribute_value_ids:
                    attr = ptav.attribute_id
                    if not attr or getattr(ptav, 'is_custom', False):
                        continue

                    key = attr.name
                    display_type = attr.display_type

                    # 🔥 SKIP file_upload from JSON
                    if display_type == "file_upload":
                        continue

                    # 🚫 SKIP Gel-coat only when Gel Coat Required != true/yes/1
                    if skip_gel_coat and key.lower() in ["gel-coat", "gel coat"]:
                        continue

                    # M2O
                    if display_type == "m2o" and ptav.m2o_res_id:
                        rec = self.env[attr.m2o_model_id.model].sudo().browse(ptav.m2o_res_id)
                        data[key] = rec.display_name
                        continue

                    # Normal
                    data[key] = ptav.name

                # Custom Attributes
                for custom in record.product_custom_attribute_value_ids:
                    ptav = custom.custom_product_template_attribute_value_id
                    if ptav and ptav.attribute_id:
                        data[ptav.attribute_id.name] = custom.custom_value

            except Exception as e:
                _logger.exception(f"❌ Error computing attributes_json: {e}")

            record.attributes_json = data
            _logger.debug(f"✅ attributes_json for Line {record.id}: {data}")

    @api.depends('product_id')
    def _compute_custom_attribute_values(self):
        """
        Checks if the product has custom attribute values associated with it,
        and if those values belong to the valid values of the product template.
        """
        for line in self:
            if not line.product_id:
                line.product_custom_attribute_value_ids = False
                continue
            if not line.product_custom_attribute_value_ids:
                continue
            valid_values = line.product_id.product_tmpl_id. \
                valid_product_template_attribute_line_ids. \
                product_template_value_ids
            # Remove the is_custom values that don't belong to this template
            for attribute in line.product_custom_attribute_value_ids:
                if attribute.custom_product_template_attribute_value_id not in valid_values:
                    line.product_custom_attribute_value_ids -= attribute
    
    @api.model
    def get_list_data(self, list_id, field_names):
        """
        Override to provide data including dynamic attributes from attributes_json
        """
        _logger.info(f"🟢 get_list_data called: list_id={list_id}, fields={field_names}")
        
        try:
            line_id = int(list_id)
        except (ValueError, TypeError):
            _logger.error("Invalid list_id: %s", list_id)
            return []

        line = self.browse(line_id)
        if not line.exists():
            _logger.warning("Line %s not found", line_id)
            return []

        row = {"id": line.id}

        for field in field_names:
            if field in self._fields:
                # Standard field
                val = line[field]
                if hasattr(val, "display_name"):
                    row[field] = val.display_name
                else:
                    row[field] = val
                _logger.info(f"✅ Standard field '{field}' = '{row[field]}'")
            else:
                # Dynamic attribute from attributes_json
                attrs = line.attributes_json or {}
                row[field] = attrs.get(field, "")
                _logger.info(f"🔵 Dynamic field '{field}' = '{row[field]}' from attributes_json")

        _logger.info(f"🟢 Final row data: {row}")
        return [row]