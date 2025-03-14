from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ProductThreeColumnWizard(models.TransientModel):
    _name = 'drkds_pl2.product_three_column_wizard'
    _description = 'Product Three Column Report Wizard'

    # Customer Information - REQUIRED
    customer_id = fields.Many2one(
        'res.partner', 
        string='Customer', 
        domain="[('customer_rank', '>', 0), ('company_id', 'in', [False, context.get('company_id', False)])]", 
        required=True,
        help="Select the customer for whom the report is being generated"
    )
    
    # Contact Selection - Optional but with dynamic domain
    contact_id = fields.Many2one(
        'res.partner', 
        string='Contact Person', 
        domain="[('parent_id', '=', customer_id), ('type', '=', 'contact'), ('company_id', 'in', [False, context.get('allowed_company_ids', [0])[0]])]",
        help="Optional contact person for the customer"
    )
    
   # Salesman - REQUIRED
    salesman_id = fields.Many2one(
        'res.users', 
        string='Salesperson', 
        domain="[('share', '=', False), ('company_id', 'in', [False, context.get('allowed_company_ids', [0])[0]])]",
        required=True,
        default=lambda self: self.env.user,
        help="Select the salesperson responsible for this report"
    )
    
    # Price Level Selection
    price_level = fields.Selection(
        [
            ('1', 'Price Level 1'),
            ('2', 'Price Level 2'),
            ('3', 'Price Level 3'),
            ('4', 'Price Level 4'),
            ('all', 'All Price Levels')
        ], 
        string='Price Level', 
        default='all', 
        required=True,
        help="Select the price level for the report"
    )
    
    # Document Reference
    doc_id = fields.Many2one(
        'mrp.bom.cost.calculator', 
        string='Source Document', 
        readonly=True,
        help="Reference to the source cost calculation document"
    )
    
    # Multi-Product Flag
    is_multi_product = fields.Boolean(
        related='doc_id.is_multi_product', 
        readonly=True,
        help="Indicates if the source document contains multiple products"
    )

    # Validation Constraints
    @api.constrains('customer_id', 'salesman_id')
    def _check_customer_salesman_company(self):
        """Ensure customer and salesman are in the current company"""
        for record in self:
            # Check customer company
            if record.customer_id.company_id and \
               record.customer_id.company_id != self.env.company:
                raise ValidationError(_(
                    "Selected customer is not associated with the current company."
                ))
            
            # Check salesman company
            if record.salesman_id.company_id and \
               record.salesman_id.company_id != self.env.company:
                raise ValidationError(_(
                    "Selected salesperson is not associated with the current company."
                ))

    @api.onchange('customer_id')
    def _onchange_customer_id(self):
        """Reset contact when customer changes"""
        self.contact_id = False
        
        # Suggest default contact if exists
        if self.customer_id:
            default_contact = self.env['res.partner'].search([
                ('parent_id', '=', self.customer_id.id),
                ('type', '=', 'contact')
            ], limit=1)
            if default_contact:
                self.contact_id = default_contact

    def action_print_report(self):
        """Generate comprehensive report with detailed logging"""
        self.ensure_one()
        
        # Validate required fields
        if not self.customer_id or not self.salesman_id:
            raise ValidationError(_("Customer and Salesperson are required."))
        
        # Create detailed report log
        report_log = self.env['drkds_pl2.product_report_log'].create({
            'customer_id': self.customer_id.id,
            'contact_id': self.contact_id.id if self.contact_id else False,
            'salesman_id': self.salesman_id.id,
            'price_level': self.price_level,
            'doc_id': self.doc_id.id,
        })
        
        # Prepare comprehensive report data
        report_data = {
            'ids': self.ids,
            'model': self._name,
            'form': {
                'customer_id': self.customer_id.id,
                'customer_name': self.customer_id.name,
                'contact_id': self.contact_id.id if self.contact_id else False,
                'contact_name': self.contact_id.name if self.contact_id else '',
                'salesman_id': self.salesman_id.id,
                'salesman_name': self.salesman_id.name,
                'salesman_email': self.salesman_id.email,
                'salesman_mobile': self.salesman_id.partner_id.mobile,
                'price_level': self.price_level,
                'doc_id': self.doc_id.id,
                'is_multi_product': self.is_multi_product,
                'report_log_id': report_log.id,
            }
        }
        
        # Generate and return report action
        return self.env.ref('drkds_pl2.action_report_product_three_column').report_action(
            self.doc_id, 
            data=report_data
        )