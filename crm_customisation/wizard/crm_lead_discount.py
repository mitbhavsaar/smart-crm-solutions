# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError

class CrmLeadDiscount(models.TransientModel):
    _name = 'crm.lead.discount'
    _description = 'CRM Lead Discount Wizard'

    lead_id = fields.Many2one('crm.lead', string='Lead', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='lead_id.company_id')
    currency_id = fields.Many2one(related='lead_id.company_id.currency_id')

    discount_type = fields.Selection([
        ('sol_discount', 'On All Order Lines'),
        ('so_discount', 'Global Discount'),
        ('amount', 'Fixed Amount'),
    ], string='Discount Type', default='sol_discount', required=True)

    discount_percentage = fields.Float(string='Discount Percentage', default=0.0)
    discount_amount = fields.Monetary(string='Discount Amount', currency_field='currency_id', default=0.0)

    def action_apply_discount(self):
        self.ensure_one()
        if self.discount_type == 'sol_discount':
            self.lead_id.material_line_ids.write({'discount': self.discount_percentage * 100})
        elif self.discount_type == 'so_discount':
            if self.discount_percentage:
                self._create_discount_line(percentage=self.discount_percentage)
        elif self.discount_type == 'amount':
            if self.discount_amount:
                self._create_discount_line(amount=self.discount_amount)
        return {'type': 'ir.actions.act_window_close'}

    def _create_discount_line(self, percentage=None, amount=None):
        self.ensure_one()
        # Search for a generic discount product or create one
        discount_product = self.env['product.product'].search([('name', '=', 'Discount'), ('type', '=', 'service')], limit=1)
        if not discount_product:
            discount_product = self.env['product.product'].create({
                'name': 'Discount',
                'type': 'service',
                'list_price': 0.0,
                'sale_ok': True,
                'crm_enabled': True,
            })

        if percentage is not None:
            # Calculate total before discount (sum of lines excluding existing discount lines)
            lines = self.lead_id.material_line_ids.filtered(lambda l: l.product_id != discount_product)
            total_before_discount = sum(lines.mapped('total_price'))
            discount_val = -(total_before_discount * percentage)
            description = _("Discount (%(percent)s%%)", percent=round(percentage * 100, 2))
        else:
            discount_val = -amount
            description = _("Discount (Fixed Amount)")

        self.env['crm.material.line'].create({
            'lead_id': self.lead_id.id,
            'product_template_id': discount_product.product_tmpl_id.id,
            'product_id': discount_product.id,
            'description': description,
            'quantity': 1.0,
            'price': discount_val,
        })
