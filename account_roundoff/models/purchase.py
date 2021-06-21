# -*- coding: utf-8 -*-
import math

from odoo import api, fields, models, _

class PurchaseOrder(models.Model):
    _inherit="purchase.order"

    apply_round_off = fields.Boolean('Apply round off', default=True)
    amount_round_off = fields.Monetary(string='Roundoff Amount', store=True, readonly=True, compute='_amount_all')
    is_enabled_roundoff = fields.Boolean('Apply Roundoff', default=lambda self: self.env["ir.config_parameter"].sudo().get_param("account.invoice_roundoff"))

    @api.model
    def create(self, vals):
        
        
        rslt = super(PurchaseOrder, self).create(vals)
        #rslt['is_enabled_roundoff']=True
        print(vals)
        #super(PurchaseOrder, self)._amount_all()
        return rslt
             


    @api.onchange('is_enabled_roundoff')
    def onchange_is_enabled_roundoff(self):
        self._amount_all()

    @api.depends('order_line.price_total')
    def _amount_all(self):
        for order in self:
            amount_untaxed = amount_tax = 0.0; amount_round_off = 0.0
            for line in order.order_line:
                amount_untaxed += line.price_subtotal
                amount_tax += line.price_tax
            order.update({
                'amount_untaxed': order.currency_id.round(amount_untaxed),
                'amount_tax': order.currency_id.round(amount_tax),
                'amount_total': amount_untaxed + amount_tax,
            })
            sales_taxes = 0
            other_taxes = 0
            if order.is_enabled_roundoff == True:
                for line in order.order_line:
                    for tax in line.taxes_id:
                        if tax.other_tax == True:
                            other_taxes += tax.amount * line.price_subtotal / 100
                        else:
                            sales_taxes += tax.amount * line.price_subtotal / 100
                val1 = sales_taxes
                if (float(val1) % 1) >= 0.5:
                    total_sales = math.ceil(val1)

                elif (float(val1) % 1) < 0.5 and (float(val1) % 1) > 0:
                    total_sales = round(val1) + 0.5
                else:
                    total_sales = val1

                val2 = other_taxes
                if (float(val2) % 1) >= 0.5:
                    total_other = math.ceil(val2)

                elif (float(val2) % 1) < 0.5 and (float(val2) % 1) > 0:
                    total_other = round(val2) + 0.5
                else:
                    total_other = val2

                total_taxes = total_sales + total_other
                if order.amount_tax and total_taxes:
                    amount_round_off = total_taxes - order.amount_tax
                    order.update({
                        'amount_total': amount_untaxed + total_taxes,
                        'amount_round_off': amount_round_off})
                else:
                    order.update({
                        'amount_total': order.amount_total,
                        'amount_round_off': 0.00})
            # else:
            #     if order.is_enabled_roundoff == False:
            #         order.update({
            #             'amount_untaxed': order.currency_id.round(amount_untaxed),
            #             'amount_tax': order.currency_id.round(amount_tax),
            #             'amount_total': amount_untaxed + amount_tax,
            #             'amount_round_off': 0.0
            #         })
        #super(PurchaseOrder, self)._amount_all()

        return True