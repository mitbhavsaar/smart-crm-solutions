from odoo import models, fields ,api
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    enable_reminder = fields.Boolean(
        string="Enable Reminder Email",
        required=True
    )
    reminder_days = fields.Integer(
        string="Reminder Days Before End Date",
        required=True
    )

    group_crm_discount = fields.Boolean(
        string="Discounts",
        implied_group='crm_customisation.group_crm_discount'
    )
    @api.constrains('reminder_days')
    def _check_reminder_days(self):
        for rec in self:
            if rec.reminder_days <= 0:
                raise ValidationError("Reminder Days must be greater than 0.")

    def set_values(self):
        super().set_values()
        IrConfig = self.env['ir.config_parameter'].sudo()
        IrConfig.set_param('crm_customisation.enable_reminder', self.enable_reminder)
        IrConfig.set_param('crm_customisation.reminder_days', self.reminder_days)

    @api.model
    def get_values(self):
        res = super().get_values()
        IrConfig = self.env['ir.config_parameter'].sudo()
        res.update({
            'enable_reminder': IrConfig.get_param('crm_customisation.enable_reminder', False),
            'reminder_days': int(IrConfig.get_param('crm_customisation.reminder_days', 0)),
        })
        return res