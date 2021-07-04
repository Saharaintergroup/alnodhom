import math

from odoo.tools import float_is_zero, float_round
from odoo.exceptions import UserError
from odoo import fields, models, api, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    invoice_roundoff = fields.Boolean(string='Allow rounding of invoice amount', help="Allow rounding of invoice amount")
    roundoff_account_id = fields.Many2one('account.account', string='Roundoff Account', implied_group='account.roundoff_account_id')

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        params = self.env['ir.config_parameter'].sudo()
        res.update(
            roundoff_account_id=int(params.get_param('account.roundoff_account_id', default=False)) or False,
            invoice_roundoff=params.get_param('account.invoice_roundoff') or False,
        )
        return res

    def set_values(self):
        self.ensure_one()
        super(ResConfigSettings, self).set_values()
        self.env['ir.config_parameter'].sudo().set_param("account.roundoff_account_id", self.roundoff_account_id.id or False)
        self.env['ir.config_parameter'].sudo().set_param("account.invoice_roundoff", self.invoice_roundoff)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    is_roundoff_line = fields.Boolean('Roundoff Line', default=False)

class AccountMove(models.Model):
    _inherit = 'account.move'

    round_off_value = fields.Monetary(string='Round off amount', store=True, readonly=True, compute='_compute_amount')
    round_off_amount = fields.Float(string='Round off Amount')
    rounded_total = fields.Monetary(string='Rounded Total', store=True, readonly=True, compute='_compute_amount')
    round_active = fields.Boolean('Enabled Roundoff', default=lambda self: self.env["ir.config_parameter"].sudo().get_param("account.invoice_roundoff"))


    @api.depends(
        'invoice_line_ids.debit',
        'invoice_line_ids.credit',
        'invoice_line_ids.currency_id',
        'invoice_line_ids.amount_currency',
        'invoice_line_ids.amount_residual',
        'invoice_line_ids.amount_residual_currency',
        'invoice_line_ids.payment_id.state',
        'invoice_line_ids.product_id',
        # 'line_ids.partner_id',
        'partner_id','invoice_line_ids.product_id')
    def _compute_amount(self):
        invoice_ids = [move.id for move in self if move.id and move.is_invoice(include_receipts=True)]
        self.env['account.payment'].flush(['state'])
        if invoice_ids:
            self._cr.execute(
                '''
                    SELECT move.id
                    FROM account_move move
                    JOIN account_move_line line ON line.move_id = move.id
                    JOIN account_partial_reconcile part ON part.debit_move_id = line.id OR part.credit_move_id = line.id
                    JOIN account_move_line rec_line ON
                        (rec_line.id = part.credit_move_id AND line.id = part.debit_move_id)
                        OR
                        (rec_line.id = part.debit_move_id AND line.id = part.credit_move_id)
                    JOIN account_payment payment ON payment.id = rec_line.payment_id
                    JOIN account_journal journal ON journal.id = rec_line.journal_id
                    WHERE move.payment_state IN ('posted', 'sent')
                   
                    AND move.id IN %s
                ''', [tuple(invoice_ids)]
            )
            print( self._cr.fetchall())
            in_payment_set = set(res[0] for res in self._cr.fetchall())
            # AND journal.post_at = 'bank_rec'
        else:
            in_payment_set = {}

        for move in self:
            total_untaxed = 0.0;  total_untaxed_currency = 0.0; total_tax = 0.0; total_tax_currency = 0.0
            total_residual = 0.0; total_residual_currency = 0.0; total = 0.0; total_currency = 0.0;amount_round_off =0.00
            currencies = set()
            for line in move.line_ids:
                if line.is_roundoff_line == False:
                    if line.currency_id:
                        currencies.add(line.currency_id)
                    if move.is_invoice(include_receipts=True):
                        # === Invoices ===
                        if not line.exclude_from_invoice_tab:
                            # Untaxed amount.
                            total_untaxed += line.balance
                            total_untaxed_currency += line.amount_currency
                            total += line.balance
                            total_currency += line.amount_currency
                        elif line.tax_line_id:
                            # Tax amount.
                            total_tax += line.balance
                            total_tax_currency += line.amount_currency
                            total += line.balance
                            total_currency += line.amount_currency
                        elif line.account_id.user_type_id.type in ('receivable', 'payable'):
                            # Residual amount.
                            total_residual += line.amount_residual
                            total_residual_currency += line.amount_residual_currency
                    else:
                        # === Miscellaneous journal entry ===
                        if line.debit:
                            total += line.balance
                            total_currency += line.amount_currency
            if move.move_type == 'entry' or move.is_outbound():
                sign = 1
            else:
                sign = -1
            move.amount_untaxed = sign * (total_untaxed_currency if len(currencies) == 1 else total_untaxed)
            move.amount_tax = sign * (total_tax_currency if len(currencies) == 1 else total_tax)
            move.amount_total = sign * (total_currency if len(currencies) == 1 else total)
            move.amount_residual = -sign * (total_residual_currency if len(currencies) == 1 else total_residual)
            move.amount_untaxed_signed = -total_untaxed
            move.amount_tax_signed = -total_tax
            move.amount_total_signed = abs(total) if move.move_type == 'entry' else -total
            move.amount_residual_signed = total_residual

            # Round off amoount updates
            sales_taxes = 0
            other_taxes = 0
            other_taxes_depends = 0
            val1 = 0
            val2 = 0
            if move.round_active and move.amount_tax:
                # amount_total = round((move.amount_total))
                for line in move.line_ids:
                    for tax in line.tax_ids:
                        if tax.amount_type == 'other_tax':
                            other_taxes_depends += (tax.depends_tax.amount / 100) * line.price_subtotal
                            other_taxes += (tax.amount / 100) * other_taxes_depends
                            val2 += float_round(other_taxes, precision_rounding=tax.rounding,
                                                rounding_method=tax.rounding_method)
                        else:
                            sales_taxes += (tax.amount / 100) * line.price_subtotal
                            val1 += float_round(sales_taxes, precision_rounding=tax.rounding,
                                                rounding_method=tax.rounding_method)

                total_taxes = val1 + val2
                if move.amount_tax and total_taxes:
                    amount_round_off = total_taxes - move.amount_tax
                    move.round_off_value = amount_round_off
                    move.round_off_amount = amount_round_off
                    move.rounded_total = move.amount_untaxed + total_taxes
                    move.amount_total = move.amount_untaxed + total_taxes
                    move.amount_total_signed = abs(total) if move.move_type == 'entry' else -total
                else:
                    move.round_off_value = 0.00
                    move.round_off_amount = 0.00
                    move.rounded_total =0.00
            currency = len(currencies) == 1 and currencies.pop() or move.company_id.currency_id
            is_paid = currency and currency.is_zero(move.amount_residual) or not move.amount_residual
            # Compute 'invoice_payment_state'.
            if move.move_type == 'entry':
                move.payment_state = False
            elif move.state == 'posted' and is_paid:
                if move.id in in_payment_set:
                    move.payment_state = 'in_payment'
                else:
                    move.payment_state = 'paid'
            else:
                move.payment_state = 'not_paid'
            for record in move.invoice_line_ids:
                if record.is_roundoff_line == True and amount_round_off:
                    record.update({'price_unit': amount_round_off})
                    for lines in self.line_ids:
                        if lines.account_id.user_type_id.type in ('Receivable', 'receivable'):
                            lines.update({'debit': move.amount_total})
                            break
                        elif lines.account_id.user_type_id.type in ('Payable', 'payable'):
                            lines.update({'credit': move.amount_total})
                            break

    def _construct_values(self, account_id, accountoff_amount):
        values = [0, 0, {
            'name': 'Roundoff Amount',
            'account_id': account_id,
            'quantity': 1,
            'price_unit': accountoff_amount,
            'display_type': False,
            'is_roundoff_line': True,
            'exclude_from_invoice_tab': False,
            'is_rounding_line': False,
            #'predict_override_default_account': False,
            'predict_from_name': False,
        }]
        return values

    @api.model_create_multi
    def create(self, vals_list):
        # OVERRIDE
        if vals_list:
            if 'invoice_line_ids' in vals_list[0].keys():
                account_id = int(self.env['ir.config_parameter'].sudo().get_param("account.roundoff_account_id"))
                accountoff_amount = 0.00
                if self.env.context.get('active_id') and self.env.context.get('active_model') == 'sale.order':
                    sale = self.env['sale.order'].browse(self.env.context.get('active_id'))
                    if sale and sale.is_enabled_roundoff:
                        accountoff_amount = sale.amount_round_off
                    if accountoff_amount:
                        values = self._construct_values(account_id, accountoff_amount)
                        vals_list[0]['invoice_line_ids'].append(values)
                else:
                    if vals_list[0].get('round_active') ==True and vals_list[0].get('round_off_amount'):
                        # If rounding amount is available, then update the total amount and add the roundoff value as new line.
                        account_id = int(self.env['ir.config_parameter'].sudo().get_param("account.roundoff_account_id"))
                        flag=False
                        for record in vals_list[0].get('line_ids'):
                            if record[2]['account_id']:
                                account = self.env['account.account'].browse(record[2]['account_id'])
                                # Update the values for the sale order
                                if account.user_type_id.type in ('Receivable', 'receivable'):
                                    if vals_list[0]['round_off_amount'] <0.0:
                                        total=abs(record[2]['price_unit']) - abs(vals_list[0]['round_off_amount'])
                                    else:
                                        total = abs(record[2]['price_unit']) + abs(vals_list[0]['round_off_amount'])
                                    record[2]['price_unit']=-total
                                    record[2]['debit'] = total
                                    flag=True
                                # Update the values for the purchase order
                                elif account.user_type_id.type in ('Payable', 'payable'):
                                    if vals_list[0]['round_off_amount'] < 0.0:
                                        total = abs(record[2]['price_unit']) - abs(vals_list[0]['round_off_amount'])
                                    else:
                                        total = abs(record[2]['price_unit']) + abs(vals_list[0]['round_off_amount'])
                                    record[2]['price_unit'] = -total
                                    record[2]['credit'] = total
                                    flag = True
                        if flag ==True:
                            values = self._construct_values(account_id, vals_list[0]['round_off_amount'])
                            vals_list[0]['line_ids'].append(values)
                            vals_list[0]['invoice_line_ids'].append(values)
            if any('state' in vals and vals.get('state') == 'posted' for vals in vals_list):
                raise UserError(_('You cannot create a move already in the posted state. Please create a draft move and post it after.'))
            vals_list = self._move_autocomplete_invoice_lines_create(vals_list)
        return super(AccountMove, self).create(vals_list)


class AccountTax(models.Model):
    _inherit = 'account.tax'

    other_tax = fields.Boolean("Other Tax")
    rounding = fields.Float(string='Rounding Precision', required=True, default=0.001,
                            help='Represent the non-zero value smallest coinage (for example, 0.05).',digits=(16, 3))
    rounding_method = fields.Selection(string='Rounding Method', required=True,
                                       selection=[('UP', 'UP'), ('DOWN', 'DOWN'), ('HALF-UP', 'HALF-UP')],
                                       default='HALF-UP',
                                       help='The tie-breaking rule used for float rounding operations')

    depends_tax = fields.Many2one('account.tax',"Depends Tax")

    amount_type = fields.Selection(default='percent', string="Tax Computation", required=True,
                                   selection=[('group', 'Group of Taxes'), ('fixed', 'Fixed'),
                                              ('percent', 'Percentage of Price'),
                                              ('division', 'Percentage of Price Tax Included'),
                                              ('other_tax', 'Depends on other Tax')],
                                   help="""
        - Group of Taxes: The tax is a set of sub taxes.
        - Fixed: The tax amount stays the same whatever the price.
        - Percentage of Price: The tax amount is a % of the price:
            e.g 100 * (1 + 10%) = 110 (not price included)
            e.g 110 / (1 + 10%) = 100 (price included)
        - Percentage of Price Tax Included: The tax amount is a division of the price:
            e.g 180 / (1 - 10%) = 200 (not price included)
            e.g 200 * (1 - 10%) = 180 (price included)
            """)

    def _compute_amount(self, base_amount, price_unit, quantity=1.0, product=None, partner=None):
        """ Returns the amount of a single tax. base_amount is the actual amount on which the tax is applied, which is
            price_unit * quantity eventually affected by previous taxes (if tax is include_base_amount XOR price_include)
        """
        self.ensure_one()

        if self.amount_type == 'fixed':
            # Use copysign to take into account the sign of the base amount which includes the sign
            # of the quantity and the sign of the price_unit
            # Amount is the fixed price for the tax, it can be negative
            # Base amount included the sign of the quantity and the sign of the unit price and when
            # a product is returned, it can be done either by changing the sign of quantity or by changing the
            # sign of the price unit.
            # When the price unit is equal to 0, the sign of the quantity is absorbed in base_amount then
            # a "else" case is needed.
            if base_amount:
                return math.copysign(quantity, base_amount) * self.amount
            else:
                return quantity * self.amount

        price_include = self._context.get('force_price_include', self.price_include)

        # base * (1 + tax_amount) = new_base
        if self.amount_type == 'percent' and not price_include:
            print("base",base_amount)
            return base_amount * self.amount / 100
        # <=> new_base = base / (1 + tax_amount)
        if self.amount_type == 'percent' and price_include:
            return base_amount - (base_amount / (1 + self.amount / 100))
        # base / (1 - tax_amount) = new_base
        if self.amount_type == 'division' and not price_include:
            return base_amount / (1 - self.amount / 100) - base_amount if (1 - self.amount / 100) else 0.0
        # <=> new_base * (1 - tax_amount) = base
        if self.amount_type == 'division' and price_include:
            return base_amount - (base_amount * (self.amount / 100))

        if self.amount_type == 'other_tax' and not price_include:
            return (base_amount * self.depends_tax.amount / 100 ) * (self.amount/100)