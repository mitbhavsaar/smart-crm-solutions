# -*- coding: utf-8 -*-
from odoo import api, fields, models
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

            # Dependency: Gel Coat Required == true/yes → then show Gel-coat
            gel_coat_required = selected_attributes.get("Gel Coat Required", "").lower()
            # Check for "true", "yes", "1" etc.
            skip_gel_coat = gel_coat_required not in ["true", "yes", "1", "required"]

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
        'product_template_id'
    )
    def _compute_attributes_json(self):
        """Attributes JSON WITHOUT file upload"""
        for record in self:
            data = {}
            
            try:
                # 1. Get all selected PTAVs for this record
                selected_ptavs = record.product_template_attribute_value_ids
                
                # 2. Iterate through TEMPLATE lines to ensure correct order
                if record.product_template_id:
                    # Track usage of attribute names to handle duplicates (e.g. multiple UOMs)
                    attr_name_counts = {}

                    for ptal in record.product_template_id.attribute_line_ids:
                        attr = ptal.attribute_id
                        
                        # Find selected value for this line
                        # We filter selected_ptavs to find the one belonging to this line
                        ptav = selected_ptavs.filtered(lambda v: v.attribute_line_id == ptal)
                        
                        if not ptav:
                            continue
                        
                        # Handle multi-select (though usually 1 per line for these types)
                        # For JSON map, we'll take the first one or join them? 
                        # Configurator usually enforces single select for these types.
                        ptav = ptav[0]

                        if getattr(ptav, 'is_custom', False):
                            # Custom values handled separately or here?
                            # Original code skipped is_custom here and handled it in loop below.
                            # But we want to maintain ORDER.
                            # Let's check if we can get the custom value here.
                            pass

                        display_type = attr.display_type
                        
                        # 🔥 SKIP file_upload from JSON
                        if display_type == "file_upload":
                            continue

                        # 🔥 SKIP is_quantity attributes
                        if attr.is_quantity:
                            continue

                        # Generate Unique Key
                        base_key = attr.name
                        count = attr_name_counts.get(base_key, 0)
                        if count == 0:
                            key = base_key
                        else:
                            key = f"{base_key}__{count}"
                        attr_name_counts[base_key] = count + 1

                        # Get Value
                        value = ""
                        if ptav.is_custom:
                            # Find custom value
                            custom_val = record.product_custom_attribute_value_ids.filtered(
                                lambda c: c.custom_product_template_attribute_value_id == ptav
                            )
                            if custom_val:
                                value = custom_val[0].custom_value
                        elif display_type == "m2o" and ptav.m2o_res_id:
                            rec_m2o = self.env[attr.m2o_model_id.model].sudo().browse(ptav.m2o_res_id)
                            value = rec_m2o.display_name
                        else:
                            value = ptav.name

                        if value:
                            data[key] = value

                # 3. Smart Sort: Move "Name UOM" next to "Name"
                # Convert to list of items to manipulate order
                items = list(data.items())
                final_items = []
                processed_keys = set()
                
                # Helper to find UOM item for a given base key
                def get_uom_item(base_key):
                    # Check for "BaseKey UOM" or "BaseKey Uom"
                    for k, v in items:
                        if k in processed_keys:
                            continue
                        if k.lower() == f"{base_key} uom".lower():
                            return (k, v)
                    return None

                for key, value in items:
                    if key in processed_keys:
                        continue
                    
                    final_items.append((key, value))
                    processed_keys.add(key)
                    
                    # Check if this key has a corresponding UOM
                    uom_item = get_uom_item(key)
                    if uom_item:
                        final_items.append(uom_item)
                        processed_keys.add(uom_item[0])
                
                # Reconstruct dict with new order
                data = dict(final_items)

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