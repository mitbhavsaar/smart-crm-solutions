from odoo import models, fields ,api
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    enable_crm_quotation_templates = fields.Boolean(
            string="CRM Quotation Templates",
        )
    crm_quotation_template_id = fields.Many2one(
        'crm.quotation.template',
        string="Default CRM Quotation Template",
    )


    def set_values(self):
        super().set_values()
        IrConfig = self.env['ir.config_parameter'].sudo()
        IrConfig.set_param('crm_spreadsheet_enhancement.enable_crm_quotation_templates', self.enable_crm_quotation_templates)
        IrConfig.set_param('crm_spreadsheet_enhancement.crm_quotation_template_id', str(self.crm_quotation_template_id.id) if self.crm_quotation_template_id else '')

    @api.model
    def get_values(self):
        res = super().get_values()
        IrConfig = self.env['ir.config_parameter'].sudo()
        template_id_str = IrConfig.get_param('crm_spreadsheet_enhancement.crm_quotation_template_id', False)
        template_rec = self.env['crm.quotation.template'].browse(int(template_id_str)) if template_id_str and template_id_str.isdigit() else False
        res.update({
            'enable_crm_quotation_templates': IrConfig.get_param('crm_spreadsheet_enhancement.enable_crm_quotation_templates', False),
            'crm_quotation_template_id': template_rec,  
        })
        return res
