# wizards/partner_balance_wizard.py
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import base64
import csv
import io
import logging

_logger = logging.getLogger(__name__)

class PartnerBalanceWizard(models.TransientModel):
    _name = 'partner.balance.wizard'
    _description = 'Partner Balance Reset Wizard'
    
    name = fields.Char(string='Reference', required=True, default=lambda self: _('Balance Reset - %s') % fields.Date.today())
    date = fields.Date(string='Reset Date', required=True, default=fields.Date.today)
    journal_id = fields.Many2one('account.journal', string='Journal', required=True,
                                domain=[('type', '=', 'general')])
    adjustment_account_id = fields.Many2one('account.account', string='Adjustment Account', required=True,
                                          domain=[('deprecated', '=', False)])
    csv_file = fields.Binary(string='CSV File', required=True)
    filename = fields.Char(string='Filename')
    delimiter = fields.Selection([
        (',', 'Comma (,)'),
        (';', 'Semicolon (;)'),
        ('\t', 'Tab')
    ], string='Delimiter', default=',', required=True)
    partner_field = fields.Selection([
        ('id', 'Database ID'),
        ('ref', 'Reference'),
        ('name', 'Name')
    ], string='Partner Identifier', default='id', required=True)
    preview_line_ids = fields.One2many('partner.balance.wizard.line', 'wizard_id', string='Preview')
    state = fields.Selection([
        ('upload', 'Upload'),
        ('preview', 'Preview'),
    ], string='State', default='upload')
    
    @api.model
    def default_get(self, fields_list):
        res = super(PartnerBalanceWizard, self).default_get(fields_list)
        journal = self.env['account.journal'].search([('type', '=', 'general')], limit=1)
        if journal:
            res['journal_id'] = journal.id
            
        # Try to find an adjustment account
        adjustment_account = self.env['account.account'].search([
            ('name', 'ilike', 'adjustment'),
            ('deprecated', '=', False)
        ], limit=1)
        if adjustment_account:
            res['adjustment_account_id'] = adjustment_account.id
            
        return res
    
    def action_preview(self):
        self.ensure_one()
        if not self.csv_file:
            raise UserError(_('Please upload a CSV file.'))
            
        # Clear existing preview lines
        self.preview_line_ids.unlink()
        
        # Process CSV file
        csv_data = base64.b64decode(self.csv_file)
        csv_file = io.StringIO(csv_data.decode('utf-8'))
        reader = csv.reader(csv_file, delimiter=self.delimiter)
        
        # Get header row
        header = next(reader, None)
        if not header:
            raise UserError(_('The CSV file seems to be empty.'))
            
        # Find required columns
        try:
            partner_col = header.index('partner')
            new_balance_col = header.index('new_balance')
            # Account type is optional, default to receivable if not found
            try:
                account_type_col = header.index('account_type')
            except ValueError:
                account_type_col = None
        except ValueError:
            raise UserError(_('The CSV file must contain "partner" and "new_balance" columns.'))
            
        # Process data rows
        preview_lines = []
        for row in reader:
            if len(row) <= max(partner_col, new_balance_col):
                continue  # Skip invalid rows
                
            partner_identifier = row[partner_col].strip()
            if not partner_identifier:
                continue
                
            try:
                new_balance = float(row[new_balance_col].strip())
            except ValueError:
                continue  # Skip rows with invalid balance
                
            # Get account type if specified, default to receivable
            account_type = 'receivable'
            if account_type_col is not None and len(row) > account_type_col:
                account_type_val = row[account_type_col].strip().lower()
                if account_type_val in ['payable', 'vendor', 'supplier', 'purchase']:
                    account_type = 'payable'
                
            # Find partner
            partner = self._find_partner(partner_identifier)
            if not partner:
                continue
                
            # Calculate current balance
            current_balance = self._get_partner_balance(partner, account_type)
                
            # Create preview line
            preview_lines.append({
                'partner_id': partner.id,
                'account_type': account_type,
                'current_balance': current_balance,
                'new_balance': new_balance,
            })
            
        # Create preview lines
        for line_data in preview_lines:
            self.env['partner.balance.wizard.line'].create(dict(
                wizard_id=self.id,
                **line_data
            ))
            
        self.state = 'preview'
        
        return {
            'name': _('Partner Balance Reset'),
            'type': 'ir.actions.act_window',
            'res_model': 'partner.balance.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
    
    def _find_partner(self, identifier):
        if self.partner_field == 'id':
            try:
                partner_id = int(identifier)
                return self.env['res.partner'].browse(partner_id).exists()
            except ValueError:
                return False
        elif self.partner_field == 'ref':
            return self.env['res.partner'].search([('ref', '=', identifier)], limit=1)
        elif self.partner_field == 'name':
            return self.env['res.partner'].search([('name', '=', identifier)], limit=1)
        return False
    
    def _get_partner_balance(self, partner, account_type='receivable'):
        if not partner:
            return 0.0
            
        # Calculate receivable balance
        receivable_domain = [
            ('partner_id', '=', partner.id),
            ('account_id.account_type', 'in', ['asset_receivable']),
            ('move_id.state', '=', 'posted'),
            ('date', '<=', self.date)
        ]
        
        receivable_lines = self.env['account.move.line'].search(receivable_domain)
        receivable_balance = sum(receivable_lines.mapped('balance'))
        
        # Calculate payable balance
        payable_domain = [
            ('partner_id', '=', partner.id),
            ('account_id.account_type', 'in', ['liability_payable']),
            ('move_id.state', '=', 'posted'),
            ('date', '<=', self.date)
        ]
        
        payable_lines = self.env['account.move.line'].search(payable_domain)
        payable_balance = sum(payable_lines.mapped('balance'))
        # For payables, the balance is typically negative in Odoo, so we don't invert the sign
        
        # Calculate net position (receivables - payables)
        net_position = receivable_balance + payable_balance  # Note: payable_balance is already negative
        
        return net_position
    
    def action_reset_balances(self):
        self.ensure_one()
        if not self.preview_line_ids:
            raise UserError(_('No partner balances to reset.'))
            
        # Create reset record
        reset_vals = {
            'name': self.name,
            'date': self.date,
            'journal_id': self.journal_id.id,
            'adjustment_account_id': self.adjustment_account_id.id,
            'line_ids': [(0, 0, {
                'partner_id': line.partner_id.id,
                'account_type': line.account_type,
                'current_balance': line.current_balance,
                'new_balance': line.new_balance,
            }) for line in self.preview_line_ids]
        }
        
        reset = self.env['partner.balance.reset'].create(reset_vals)
        
        # Process reset
        reset.action_reset_balances()
        
        # Show the reset record
        return {
            'name': _('Partner Balance Reset'),
            'type': 'ir.actions.act_window',
            'res_model': 'partner.balance.reset',
            'view_mode': 'form',
            'res_id': reset.id,
            'target': 'current',
        }


class PartnerBalanceWizardLine(models.TransientModel):
    _name = 'partner.balance.wizard.line'
    _description = 'Partner Balance Wizard Line'
    
    wizard_id = fields.Many2one('partner.balance.wizard', string='Wizard', ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string='Partner', required=True)
    account_type = fields.Selection([
        ('receivable', 'Receivable'),
        ('payable', 'Payable')
    ], string='Account Type', required=True, default='receivable')
    current_balance = fields.Float(string='Current Balance', readonly=True)
    new_balance = fields.Float(string='New Balance')
    adjustment_amount = fields.Float(string='Adjustment Amount', compute='_compute_adjustment_amount')
    
    @api.depends('current_balance', 'new_balance')
    def _compute_adjustment_amount(self):
        for record in self:
            record.adjustment_amount = record.new_balance - record.current_balance