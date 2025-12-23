# -*- coding: utf-8 -*-
{
    'name': 'CRM Advanced Solution',
    'version': '18.0.1.0.10',
    'summary': 'Advanced material tracking with seamless sales integration, intelligent spreadsheets, and automated manufacturing reminders.',
    'description': '''
       Default List View.
       Additional Contacts Tab.
       Contact Form Enhancements & Auto-Fill Address Using Pincode.
    ''',
    'category': 'Uncategorized',
    'author': 'Entrivis Tech',
    'company': 'Entrivis Tech',
    'maintainer': 'Entrivis Tech',
    'website': 'https://www.entrivistech.com',
    'depends': [
        'base','crm','sale_management','product','mail','stock','mrp'],
    
    'images': ['/static/description/icon.png'],
    'data': [
        "security/ir.model.access.csv",
        "wizard/crm_lead_discount_views.xml",
        "security/ecpl_security.xml",
        "data/ir_sequence_data.xml",
        "data/reminder_email_cron.xml",
        "data/manufacturing_reminder_email.xml",
        # "data/email_template_crm_delivery_request.xml",
        "views/crm_lead_views.xml",
        "views/res_config_settings_view.xml",
        "views/res_partner_view.xml",
        # "views/product_category_view.xml",
        "views/product_template_view.xml",
        "views/mrp_views.xml",
        "views/sale_views.xml",
        # "views/delivery_date_portal_template.xml",   
    ],
    'external_dependencies': {
        'python': ['openpyxl'],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
