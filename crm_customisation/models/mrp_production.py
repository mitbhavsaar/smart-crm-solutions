from datetime import timedelta, datetime, time
from odoo import models, fields, api
from odoo.exceptions import ValidationError

import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"


    sale_order_id = fields.Many2one('sale.order', compute="_compute_sale_order", store=False)
    ask_for_delivery_date = fields.Boolean(string="Ask for Delivery Date",readonly=True)
    delivery_date = fields.Date(string="Expected Delivery Date", readonly=True)
    email_reminder_sent = fields.Boolean(string="Email Reminder Sent", default=False)
    
    def _compute_sale_order(self):
        for mo in self:
            mo.sale_order_id = self.env['sale.order'].search([('name', '=', mo.origin)], limit=1)




    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            product_id = vals.get("product_id")



        return super().create(vals_list)

    def send_mo_reminder_email(self):

        # Fetch settings safely
        IrConfig = self.env['ir.config_parameter'].sudo()
        enable_reminder = IrConfig.get_param('crm_customisation.enable_reminder', 'False') == 'True'
        reminder_days = int(IrConfig.get_param('crm_customisation.reminder_days', 0))

        if not enable_reminder or reminder_days <= 0:
            return

        today = fields.Date.today()
        target_date = today + timedelta(days=reminder_days)

        user_tz = self.env.user.tz or 'UTC'
        start_dt_local = datetime.combine(target_date, time.min)
        end_dt_local = datetime.combine(target_date, time.max)

        start_dt = fields.Datetime.context_timestamp(self.with_context(tz=user_tz), start_dt_local)
        end_dt = fields.Datetime.context_timestamp(self.with_context(tz=user_tz), end_dt_local)

        mos = self.env['mrp.production'].search([
            ('state', '=', 'confirmed'),
            ('date_finished', '>=', start_dt),
            ('date_finished', '<=', end_dt),
            ('origin', '!=', False),
            ('email_reminder_sent', '=', False),
        ])


        template = self.env.ref('crm_customisation.email_template_mo_reminder', raise_if_not_found=False)
        if not template:
            return

        for mo in mos:
            so = self.env['sale.order'].search([('name', '=', mo.origin)], limit=1)
            if not so or not so.user_id or not so.user_id.email:
                continue

            email_to = so.user_id.email
            try:
                template.send_mail(
                    mo.id,
                    force_send=True,
                    raise_exception=False,
                    email_values={'email_to': email_to}
                )
                mo.email_reminder_sent = True
            except Exception as e:
                return

