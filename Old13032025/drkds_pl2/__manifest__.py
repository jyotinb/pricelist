
{
    'name': 'Advanced BOM Cost Calculator',
    'version': '17.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Advanced cost calculation for Bill of Materials including nested BOMs and operations',
    'description': """
        Advanced BOM Cost Calculator
        ==========================
        * Calculate costs for nested BOMs
        * Include operation costs
        * Detailed cost breakdown
        * Cost tracking at each BOM level
        * Safe handling of recursive BOMs
        * Review and apply costs
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': ['base', 'sale','mrp', 'stock', 'product','drkds_pl_product','drkds_rm_prices'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/mrp_bom_cost_calculator_data.xml',
        'wizard/product_selection_wizard_view.xml',
        'wizard/product_additional_cost_wizard_view.xml',
        'wizard/product_three_column_wizard_views.xml',
        #'wizard/raw_materials_editor_view.xml',
        'views/bom_cost_calculator_views.xml',
        'report/bom_cost_calculator_report.xml',
        'report/bom_cost_calculator_report_template.xml',
        'report/report_registration.xml',
        'report/report_actions.xml',
        'report/report_templates.xml',
        'views/bom_cost_calculator_view.xml',
        'report/report_templates.xml',
        'views/report_log_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}