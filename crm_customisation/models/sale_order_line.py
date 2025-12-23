# -*- coding: utf-8 -*-
from odoo import api, fields, models ,_
from odoo.exceptions import UserError
import json
import logging
_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    ask_for_delivery_date = fields.Boolean(string="Ask for Delivery Date",readonly=True)
    delivery_date = fields.Date(string="Expected Delivery Date", readonly=True)
    opportunity_id = fields.Many2one(
            'crm.lead',
            string='Opportunity',
            copy=False,
            help="Opportunity from which this quotation was created"
        )
    
    spreadsheet_id = fields.Many2one('sale.order.spreadsheet', 'Quote Calculator' ,store=True)

    
    
    
    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create to handle spreadsheet creation from CRM
        """
        ctx = self.env.context
        crm_has_spreadsheet = ctx.get('crm_has_spreadsheet')
        crm_lead_id = ctx.get('crm_lead_id')
        
        _logger.info(f"🔵 [SALE CREATE] Context: crm_has_spreadsheet={crm_has_spreadsheet}, crm_lead_id={crm_lead_id}")
        
        # ✅ FIX 3: Removed unnecessary try-except that was hiding errors
        orders = super(SaleOrder, self).create(vals_list)
        
        if not orders:
            return orders
        
        # ✅ FIX 4: Set opportunity_id for tracking
        if crm_lead_id:
            for order in orders:
                if not order.opportunity_id:
                    order.opportunity_id = crm_lead_id
                    _logger.info(f"✅ Linked Sale Order {order.id} to Opportunity {crm_lead_id}")
        
        # ✅ FIX 5: Create spreadsheet with proper error handling
        if crm_has_spreadsheet and crm_lead_id:
            crm_lead = self.env['crm.lead'].browse(crm_lead_id)
            
            if not crm_lead.exists():
                _logger.warning(f"⚠️ CRM Lead {crm_lead_id} not found")
                return orders
            
            for order in orders:
                try:
                    # ✅ FIX 6: Removed time.sleep - use commit instead
                    self.env.cr.commit()
                    
                    # Refresh order to get latest data
                    fresh_order = self.env['sale.order'].browse(order.id)
                    
                    # Create spreadsheet
                    spreadsheet = crm_lead._create_sales_spreadsheet_with_data(fresh_order)
                    
                    if spreadsheet:
                        _logger.info(f"✅ Spreadsheet {spreadsheet.id} created for order {fresh_order.id}")
                    else:
                        _logger.warning(f"⚠️ Spreadsheet creation returned False for order {fresh_order.id}")
                        
                except Exception as e:
                    # ✅ FIX 7: Don't fail order creation if spreadsheet fails
                    _logger.error(f"❌ Spreadsheet creation error for order {order.id}: {e}", exc_info=True)
                    # Continue with next order
                    continue
        
        return orders
    
    def action_open_spreadsheet_common(self):
        """
        Open or create Sale Order spreadsheet
        """
        self.ensure_one()
        
        _logger.info(f"\n🔵 [OPEN SPREADSHEET] Sale Order: {self.id}, Name: {self.name}")
        
        # ✅ FIX 8: Always search for existing spreadsheet first
        spreadsheet = self.env['sale.order.spreadsheet'].search([
            ('order_id', '=', self.id)
        ], limit=1)
        
        if spreadsheet and spreadsheet.exists():
            _logger.info(f"✅ Found existing spreadsheet {spreadsheet.id}")
            return spreadsheet.action_open_spreadsheet()
        
        # ✅ FIX 9: Check if we have an opportunity with spreadsheet
        if self.opportunity_id:
            _logger.info(f"🔄 Checking opportunity {self.opportunity_id.id} for spreadsheet")
            
            crm_spreadsheet = self.env['crm.lead.spreadsheet'].search([
                ('lead_id', '=', self.opportunity_id.id),
                ('raw_spreadsheet_data', '!=', False)
            ], limit=1)
            
            if crm_spreadsheet and crm_spreadsheet.exists():
                _logger.info(f"🔄 Found CRM spreadsheet {crm_spreadsheet.id}, converting...")
                
                try:
                    # Convert CRM data to Sales format
                    sales_data_json = self.opportunity_id._convert_crm_spreadsheet_to_sales(
                        crm_spreadsheet, self
                    )
                    
                    if sales_data_json:
                        # Create new spreadsheet with converted data
                        spreadsheet = self.env['sale.order.spreadsheet'].create({
                            'name': f"{self.name} - Calculator",
                            'order_id': self.id,
                            'raw_spreadsheet_data': sales_data_json,
                        })
                        
                        _logger.info(f"✅ Created spreadsheet {spreadsheet.id} from CRM data")
                        return spreadsheet.action_open_spreadsheet()
                    else:
                        _logger.warning("⚠️ Conversion returned empty data")
                        
                except Exception as e:
                    _logger.error(f"❌ Error converting CRM spreadsheet: {e}", exc_info=True)
                    # Continue to create empty spreadsheet
        
        # ✅ FIX 10: Create empty spreadsheet as fallback
        _logger.info("📝 Creating new empty spreadsheet")
        
        try:
            spreadsheet = self.env['sale.order.spreadsheet'].create({
                'name': f"{self.name} - Calculator",
                'order_id': self.id,
            })
            
            _logger.info(f"✅ Created empty spreadsheet {spreadsheet.id}")
            return spreadsheet.action_open_spreadsheet()
            
        except Exception as e:
            _logger.error(f"❌ Failed to create spreadsheet: {e}", exc_info=True)
            raise UserError(_("Failed to create calculator: %s") % str(e))


    
    def action_confirm(self):
        result = super().action_confirm()
        for line in self.order_line:
            mos = self.env['mrp.production'].search([
                ('origin', '=', self.name),
                ('product_id', '=', line.product_id.id),
                ('state', '=', 'draft')
            ])
            for mo in mos:
                mo.write({
                    'raisin_type_id': line.raisin_type_id.id if line.raisin_type_id else False,
                    'ask_for_delivery_date': self.ask_for_delivery_date,
                    'delivery_date': self.delivery_date,
                })
        return result
    



class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"
    _description = "Sale Order Line"
    _order = "id desc"

    width = fields.Float(string="Width")
    thickness = fields.Float(string="Thickness")
    raw_material = fields.Char(string="Raw Material (Brand)")
    raisin_type_id = fields.Many2one("raisin.type", string="Raisin Type")
    height = fields.Float(string="Height")
    length = fields.Float(string="Length")

    attached_file_id = fields.Binary(
        string="Attached File",
        attachment=True,
    )
    attached_file_name = fields.Char(
        string="Attached File Name",
    )

    @api.depends('product_id', 'company_id')
    def _compute_tax_id(self):
        """Override to preserve taxes passed from CRM"""
        crm_lines = self.filtered(lambda l: l.env.context.get('from_crm_lead') and l.tax_id)
        other_lines = self - crm_lines
        
        # For CRM lines with taxes, do nothing (keep existing)
        # For other lines, call super
        if other_lines:
            super(SaleOrderLine, other_lines)._compute_tax_id()
    
    @api.onchange('product_id')
    def _onchange_product_id_set_raisin_type(self):
        """Auto-set raisin_type_id from selected product."""
        if self.product_id and self.product_id.raisin_type_id:
            self.raisin_type_id = self.product_id.raisin_type_id.id
        else:
            self.raisin_type_id = False
    
    # Inside SaleOrderLine class

    def _prepare_procurement_values(self, group_id=False):
        values = super()._prepare_procurement_values(group_id)
        sale_order = self.order_id
        if sale_order:
            values.update({
                'ask_for_delivery_date': sale_order.ask_for_delivery_date,
                'delivery_date': sale_order.delivery_date,
                'raisin_type_id': self.raisin_type_id.id if self.raisin_type_id else False,
                'attached_file_id': self.attached_file_id,
                'attached_file_name': self.attached_file_name,
            })
        return values

    
    def _prepare_mo_values(self, product_id, product_qty, product_uom, location_src_id, name, origin, values):
        res = super()._prepare_mo_values(product_id, product_qty, product_uom, location_src_id, name, origin, values)

        if values.get('raisin_type_id'):
            res['raisin_type_id'] = values['raisin_type_id']
        
        if values.get('attached_file_id'):
            res['attached_file_id'] = values['attached_file_id']
        
        if values.get('attached_file_name'):
            res['attached_file_name'] = values['attached_file_name']
        
        return res

class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _prepare_mo_values(self, product_id, product_qty, product_uom, location_src_id, name, origin, values):
        res = super()._prepare_mo_values(product_id, product_qty, product_uom, location_src_id, name, origin, values)
        if values.get('raisin_type_id'):
            res['raisin_type_id'] = values['raisin_type_id']
        return res

class SupplierInfo(models.Model):
    _inherit = "product.supplierinfo"

    partner_id = fields.Many2one(
        'res.partner', 'Vendor',
        ondelete='cascade', required=True,
        domain=[('supplier_rank', '>', 0), ('customer_rank', '=', 0)],
        check_company=True)