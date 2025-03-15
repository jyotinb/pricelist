# models/partner_balance_reset.py
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class PartnerBalanceReset(models.Model):
    _name = 'partner.balance.reset'
    _description = 'Partner Balance Reset History'
    _order = 'date desc'

    name = fields.Char(string='Reference', required=True)
    date = fields.Date(string='Reset Date', required=True)
    journal_id = fields.Many2one('account.journal', string='Journal', required=True)
    line_ids = fields.One2many('partner.balance.reset.line', 'reset_id', string='Lines')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
    ], string='Status', default='draft')
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    adjustment_account_id = fields.Many2one('account.account', string='Adjustment Account', required=True,
                                            domain=[('deprecated', '=', False)])
    journal_entry_ids = fields.Many2many('account.move', string='Journal Entries', readonly=True)
    total_adjustment = fields.Float(string='Total Adjustment', compute='_compute_total_adjustment', store=True)
    
    @api.depends('line_ids.adjustment_amount')
    def _compute_total_adjustment(self):
        for record in self:
            record.total_adjustment = sum(record.line_ids.mapped('adjustment_amount'))
    
    def action_reset_balances(self):
        self.ensure_one()
        if self.state == 'done':
            return True
            
        journal_entries = self.env['account.move']
        
        for line in self.line_ids:
            if line.adjustment_amount == 0:
                continue
                
            # Get the appropriate account based on account type
            account_id = line.account_id.id
            
            # For payable accounts, we need to reverse the debit/credit compared to receivables
            # to follow accounting conventions
            adjustment = line.adjustment_amount
            if line.account_type == 'payable':
                adjustment = -adjustment
                
            # Create journal entry
            move_vals = {
                'journal_id': self.journal_id.id,
                'date': self.date,
                'ref': f'Balance adjustment for {line.partner_id.name} ({line.account_type})',
                'line_ids': [
                    (0, 0, {
                        'partner_id': line.partner_id.id,
                        'account_id': account_id,
                        'name': f'Partner {line.account_type} balance adjustment',
                        'debit': adjustment if adjustment > 0 else 0,
                        'credit': abs(adjustment) if adjustment < 0 else 0,
                    }),
                    (0, 0, {
                        'account_id': self.adjustment_account_id.id,
                        'name': f'Partner {line.account_type} balance adjustment',
                        'debit': abs(adjustment) if adjustment < 0 else 0,
                        'credit': adjustment if adjustment > 0 else 0,
                    })
                ]
            }
            
            move = self.env['account.move'].create(move_vals)
            move.action_post()
            journal_entries += move
            
            # Update line status
            line.write({
                'state': 'done',
                'journal_entry_id': move.id
            })
            
        # Update reset record
        self.write({
            'state': 'done',
            'journal_entry_ids': [(6, 0, journal_entries.ids)]
        })
        
        return True
        
    def action_view_journal_entries(self):
        self.ensure_one()
        return {
            'name': 'Journal Entries',
            'view_mode': 'tree,form',
            'res_model': 'account.move',
            'domain': [('id', 'in', self.journal_entry_ids.ids)],
            'type': 'ir.actions.act_window',
            'context': {'create': False}
        }


class PartnerBalanceResetLine(models.Model):
    _name = 'partner.balance.reset.line'
    _description = 'Partner Balance Reset Line'
    
    reset_id = fields.Many2one('partner.balance.reset', string='Reset', ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string='Partner', required=True)
    account_type = fields.Selection([
        ('receivable', 'Receivable'),
        ('payable', 'Payable')
    ], string='Account Type', required=True, default='receivable')
    account_id = fields.Many2one('account.account', string='Account', compute='_compute_account_id', store=True)
    current_balance = fields.Float(string='Current Balance', readonly=True)
    new_balance = fields.Float(string='New Balance')
    adjustment_amount = fields.Float(string='Adjustment Amount', compute='_compute_adjustment_amount', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
    ], string='Status', default='draft')
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    
    @api.depends('current_balance', 'new_balance')
    def _compute_adjustment_amount(self):
        for record in self:
            record.adjustment_amount = record.new_balance - record.current_balance
    
    @api.depends('partner_id', 'account_type')
    def _compute_account_id(self):
        for record in self:
            if record.partner_id and record.account_type:
                if record.account_type == 'receivable':
                    record.account_id = record.partner_id.property_account_receivable_id
                else:
                    record.account_id = record.partner_id.property_account_payable_id
            else:
                record.account_id = False
    
    @api.onchange('partner_id', 'account_type')
    def _onchange_partner_or_account_type(self):
        if self.partner_id and self.account_type:
            # Get partner's current balance
            self.current_balance = self._get_partner_balance()
            self.new_balance = self.current_balance
    
    def _get_partner_balance(self):
        self.ensure_one()
        if not self.partner_id or not self.account_type:
            return 0.0
            
        # Get the balance up to the reset date
        # In Odoo 17, the internal_type field has been changed to account_type
        domain = [
            ('partner_id', '=', self.partner_id.id),
            ('account_id.account_type', 'in', ['asset_receivable' if self.account_type == 'receivable' else 'liability_payable']),
            ('move_id.state', '=', 'posted'),
            ('date', '<=', self.reset_id.date or fields.Date.today())
        ]
        
        lines = self.env['account.move.line'].search(domain)
        
        # For payable accounts, we need to invert the sign to follow accounting convention
        # (positive balance = money owed TO vendor, negative = credit from vendor)
        balance = sum(lines.mapped('balance'))
        if self.account_type == 'payable':
            balance = -balance
            
        return balance