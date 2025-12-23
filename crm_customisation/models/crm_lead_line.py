# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

import logging
_logger = logging.getLogger(__name__) 

class CrmMaterialLine(models.Model):
    _name = "crm.material.line"
    _description = "CRM Opportunity Material Line"
    _order = "id desc"
    
    partner_id = fields.Many2one('res.partner',string='Customer',related='lead_id.partner_id',store=True,readonly=True,)
    
    company_id = fields.Many2one(
    'res.company',
    string='Company',
    default=lambda self: self.env.company,
    readonly=True,
    index=True,
    )

    lead_id = fields.Many2one(
        "crm.lead",
        string="Opportunity",
    )
    pricelist_id = fields.Many2one(
    'product.pricelist',
    string='Pricelist',
    related='lead_id.partner_id.property_product_pricelist',
    store=True,
    readonly=True,
    )
    currency_id = fields.Many2one(
    'res.currency',
    related='lead_id.company_id.currency_id',
    store=True,
    readonly=True,
    )
    price = fields.Float(string = "Price")
    price_custom = fields.Monetary(
        string="Price",
        currency_field='currency_id',
        compute='_compute_price_custom',
        inverse='_inverse_price_custom',
        store=True
    )
    total_price = fields.Float(string ="Total Price" , readonly=True ,compute = "compute_total_price")

    product_template_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        domain=[('sale_ok', '=', True),('crm_enabled', '=', True)],
    )
    product_id = fields.Many2one(
        "product.product",
        string="Variant",
        readonly=True,
    )
    product_category_id = fields.Many2one(
        "product.category",
        string="Product Category",
        store=True,
    )

    product_uom_id = fields.Many2one('uom.uom', string='UOM')

    quantity = fields.Float(string="Quantity")
    width = fields.Float(string="Width")
    thickness = fields.Float(string="Thickness")
    raisin_type_id = fields.Many2one("raisin.type", string="Raisin Type")
    height = fields.Float(string="Height")
    length = fields.Float(string="Length")
    discount = fields.Float(string='Discount (%)', digits='Discount', default=0.0)
    tax_id = fields.Many2many(
        'account.tax', 
        string='Taxes',
        domain=[('type_tax_use', '=', 'sale')],
    )
    price_subtotal = fields.Monetary(
        string='Subtotal', 
        compute='_compute_totals',
        store=True,
        currency_field='currency_id'
    )

    # New: Attributes selected from configurator
    product_template_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value',
        'crm_material_line_product_template_attribute_value_rel',
        'line_id', 'value_id',
        string="Attribute Values",
    )

    product_no_variant_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value',
        'crm_material_line_no_variant_attribute_value_rel',
        'line_id', 'value_id',
        string="Extra Attribute Values"
    )

    is_configurable_product = fields.Boolean(
        string="Is Configurable",
        compute="_compute_is_configurable_product"
    )
    product_display_name = fields.Char(string="Product Display Name")
    attribute_summary = fields.Char(string="Selected Attributes Summary",compute='_compute_attribute_summary',store=True,readonly=True)
    description = fields.Text(
        string="Description",
        help="Product description with selected attributes"
    )
    attached_file_id = fields.Binary(
        string="Attached File",
        attachment=True,
    )
    attached_file_name = fields.Char(
        string="Attached File Name",
    )
    
        
    @api.depends('quantity', 'price')
    @api.depends('quantity', 'price', 'discount', 'tax_id')
    def _compute_totals(self):
        for line in self:
            price = line.price or 0.0
            qty = line.quantity or 0.0
            disc = line.discount or 0.0
            
            # Subtotal (Price * Qty * (1 - Discount))
            subtotal = price * qty * (1 - (disc / 100.0))
            line.price_subtotal = subtotal
            
            # Total Price (Subtotal + Taxes)
            taxes = line.tax_id.compute_all(
                subtotal, 
                line.currency_id, 
                1.0, 
                product=line.product_id, 
                partner=line.lead_id.partner_id
            )
            line.total_price = taxes['total_included']

    def compute_total_price(self):
        # Compatibility/Legacy call
        self._compute_totals()
            
    @api.depends('price')
    def _compute_price_custom(self):
        """Compute price_custom from price field"""
        for line in self:
            line.price_custom = line.price or 0.0
    
    def _inverse_price_custom(self):
        """Update price field when price_custom is modified"""
        for line in self:
            line.price = line.price_custom or 0.0
        
    @api.onchange('product_template_id', 'product_template_attribute_value_ids', 'product_custom_attribute_value_ids')
    def _onchange_update_description(self):
        """Update description WITHOUT file upload attribute"""
        for line in self:
            if not line.product_id:
                line.description = ""
                continue

            product = line.product_id
            template = product.product_tmpl_id
            attribute_lines = []

            # 1️⃣ Template Attribute Values
            for ptav in line.product_template_attribute_value_ids:
                attr = ptav.attribute_id
                if ptav.is_custom:
                    continue

                display_type = attr.display_type

                # 🔥 SKIP file_upload from description
                if display_type == "file_upload":
                    continue

                # M2O attribute
                if display_type == "m2o" and ptav.m2o_res_id:
                    model = attr.m2o_model_id.model
                    rec = self.env[model].sudo().browse(ptav.m2o_res_id)
                    attribute_lines.append(f"• {attr.name}: {rec.display_name}")
                    continue

                # Normal attribute
                attribute_lines.append(f"• {attr.name}: {ptav.name}")

                # Auto-populate Raisin Type
                # Check for "Raisin" or "Resin" in attribute name (case-insensitive)
                attr_name_lower = attr.name.lower()
                if "raisin" in attr_name_lower or "resin" in attr_name_lower:
                    _logger.info(f"🔍 Found Raisin/Resin attribute: {attr.name}, Value: {ptav.name}")
                    search_value = ptav.name.strip()
                    # Try exact match first
                    raisin_rec = self.env['raisin.type'].browse(ptav.m2o_res_id)
                    if not raisin_rec:
                         _logger.warning(f"⚠️ No 'raisin.type' found for value '{search_value}'. checking partial match...")
                         # Optional: Try partial match if needed, or just log failure
                    
                    if raisin_rec:
                        _logger.info(f"✅ Setting raisin_type_id to: {raisin_rec.name} (ID: {raisin_rec.id})")
                        line.raisin_type_id = raisin_rec.id
                    else:
                        _logger.warning(f"❌ Failed to find raisin.type for value: {search_value}")

            # 2️⃣ Custom Attribute Values
            for custom in line.product_custom_attribute_value_ids:
                ptav = custom.custom_product_template_attribute_value_id
                if ptav and ptav.attribute_id:
                    attribute_lines.append(f"• {ptav.attribute_id.name}: {custom.custom_value}")

            # 3️⃣ Final Description (NO FILE INFO)
            base_description = product.description_sale or template.description_sale or ""
            attribute_description = "\n".join(attribute_lines)

            if attribute_description:
                if base_description:
                    line.description = f"{base_description}\n\n📋 Selected Attributes:\n{attribute_description}"
                else:
                    line.description = f"📋 Selected Attributes:\n{attribute_description}"
            else:
                line.description = base_description


    
    @api.depends('product_template_attribute_value_ids')
    def _compute_attribute_summary(self):
        """Attribute summary WITHOUT file upload"""
        for line in self:
            summary = []
            for ptav in line.product_template_attribute_value_ids:
                # 🔥 SKIP file_upload
                if ptav.attribute_id.display_type == "file_upload":
                    continue
                    
                attr = ptav.attribute_id.name
                
                # M2O: show actual record name
                if ptav.attribute_id.display_type == "m2o" and ptav.m2o_res_id:
                    model = ptav.attribute_id.m2o_model_id.model
                    rec = self.env[model].sudo().browse(ptav.m2o_res_id)
                    val = rec.display_name
                else:
                    val = ptav.name
                    
                summary.append(f"{attr}: {val}")
            line.attribute_summary = ", ".join(summary)
            
    @api.depends('product_template_id')
    def _compute_is_configurable_product(self):
        for line in self:
            line.is_configurable_product = bool(
                line.product_template_id and line.product_template_id.attribute_line_ids
            )
    @api.constrains('product_template_id')
    def _check_product_template(self):
        for line in self:
            if not line.product_template_id:
                raise ValidationError("Product Template must be set for Material Line.")

    @api.onchange('product_template_id', 'product_template_attribute_value_ids','product_id')
    def _onchange_product_template_or_attributes(self):
        for line in self:
            if not line.product_template_id:
                line.product_id = False
                line.price = 0.0
                line.tax_id = False
                continue
            product = line.product_template_id._get_variant_for_combination(
                line.product_template_attribute_value_ids
            )
            if product:
                _logger.info(" Found variant: %s", product.id)
            else:
                _logger.warning("No matching variant for combination")
            line.product_id = product or False
            if product:
                line.product_uom_id = product.uom_id
                # Auto-populate price from product's list price
                line.price = product.list_price or 0.0
                # Auto-populate taxes from product template
                line.tax_id = product.product_tmpl_id.taxes_id
            else:
                line.product_uom_id = False
                # Use template's list price if no variant found
                line.price = line.product_template_id.list_price or 0.0
                line.tax_id = line.product_template_id.taxes_id
    

    def unlink(self):
        """Trigger sheet deletion before material lines are deleted"""
        # Store references before deletion
        spreadsheets_to_update = []
        line_ids_to_delete = []
        
        for record in self:
            if record.lead_id and record.lead_id.spreadsheet_ids:
                spreadsheets_to_update.extend(record.lead_id.spreadsheet_ids)
                line_ids_to_delete.append(record.id)
        
        res = super().unlink()
        
        # Delete sheets after successful deletion
        for spreadsheet in set(spreadsheets_to_update):
            for line_id in line_ids_to_delete:
                spreadsheet._delete_sheet_for_material_line(line_id)
        
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to handle dynamic attributes and trigger spreadsheet sync"""
        processed_vals_list = []
        # Get all model fields to correctly separate standard fields from dynamic attributes
        model_fields = set(self._fields.keys())
        
        for vals in vals_list:
            dynamic_updates = {}
            standard_vals = {}
            
            for field, value in vals.items():
                # Check if the field exists in the model
                if field in model_fields:
                    standard_vals[field] = value
                else:
                    dynamic_updates[field] = value
            
            # If there are dynamic updates, store them in attributes_json
            if dynamic_updates:
                # Merge with existing attributes_json if present
                existing_json = standard_vals.get('attributes_json', {})
                if isinstance(existing_json, dict):
                    existing_json.update(dynamic_updates)
                    standard_vals['attributes_json'] = existing_json
                else:
                    standard_vals['attributes_json'] = dynamic_updates
                
                # Also set attributes_description
                attribute_lines = []
                for attr_name, attr_value in dynamic_updates.items():
                    attribute_lines.append(f"{attr_name}: {attr_value}")
                
                # Append to existing description if present
                current_desc = standard_vals.get('attributes_description', "")
                new_desc = ", ".join(attribute_lines)
                if current_desc:
                    standard_vals['attributes_description'] = f"{current_desc}, {new_desc}"
                else:
                    standard_vals['attributes_description'] = new_desc
            
            processed_vals_list.append(standard_vals)
        
        # Create records with processed values
        records = super().create(processed_vals_list)
        
        # Trigger sync for related spreadsheets
        for record in records:
            if record.lead_id and record.lead_id.spreadsheet_ids:
                for spreadsheet in record.lead_id.spreadsheet_ids:
                    # Create sheet for the new line
                    spreadsheet.with_context(material_line_id=record.id)._dispatch_insert_list_revision()

            # Auto-populate Raisin Type if missing
            if not record.raisin_type_id and record.product_template_attribute_value_ids:
                for ptav in record.product_template_attribute_value_ids:
                    attr_name_lower = ptav.attribute_id.name.lower()
                    if "raisin" in attr_name_lower or "resin" in attr_name_lower:
                        _logger.info(f"🔍 [Create] Found Raisin/Resin attribute: {ptav.attribute_id.name}, Value: {ptav.name}")
                        search_value = ptav.m2o_res_id
                        print("search value -----------------",search_value)
                        raisin_rec = self.env['raisin.type'].browse(ptav.m2o_res_id)
                        print("resign rec ----------------------",raisin_rec)
                        if raisin_rec:
                            _logger.info(f"✅ [Create] Setting raisin_type_id to: {raisin_rec} (ID: {raisin_rec})")
                            record.raisin_type_id = raisin_rec.id
                            break
                        else:
                            _logger.warning(f"❌ [Create] Failed to find raisin.type for value: {search_value}")
        
        return records


    def write(self, vals):
        """✅ FIXED: Properly handle dynamic attributes from spreadsheet"""
        _logger.info(f"🔵 write() called with vals: {vals}")
        
        # Separate standard and dynamic fields
        dynamic_updates = {}
        standard_vals = {}
        
        # List of actual model fields
        model_fields = set(self._fields.keys())
        _logger.info(f"📋 Model fields: {model_fields}")
        
        for field, value in vals.items():
            if field in model_fields:
                # Standard field - write directly
                standard_vals[field] = value
                _logger.info(f"✅ Standard field: {field} = {value}")
            else:
                # Dynamic attribute - store in attributes_json
                dynamic_updates[field] = value
                _logger.info(f"🔵 Dynamic field: {field} = {value}")
        
        # First write standard fields
        if standard_vals:
            res = super().write(standard_vals)
        else:
            res = True
        
        # Then handle dynamic attributes
        if dynamic_updates:
            for record in self:
                # Update attributes_json
                current_map = record.attributes_json or {}
                current_map.update(dynamic_updates)
                
                # Update attributes_description
                attribute_lines = []
                for attr_name, attr_value in current_map.items():
                    attribute_lines.append(f"{attr_name}: {attr_value}")
                
                # Write attribute fields using super to avoid recursion
                super(CrmMaterialLine, record).write({
                    'attributes_json': current_map,
                    'attributes_description': ", ".join(attribute_lines)
                })
                
                _logger.info(f"✅ Updated attributes for record {record.id}: {current_map}")
        
        # Trigger spreadsheet sync
        for record in self:
            spreadsheet_ids = getattr(record.lead_id, 'spreadsheet_ids', False)
            if record.lead_id and spreadsheet_ids:
                for spreadsheet in spreadsheet_ids:
                    spreadsheet._sync_sheets_with_material_lines()
        
        return res
    
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