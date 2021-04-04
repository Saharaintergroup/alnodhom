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
            if order.is_enabled_roundoff == True:
                val = order.amount_tax
                if (float(val) % 1) >= 0.5:
                    amount_total = math.ceil(val)
                elif (float(val) % 1) < 0.5 and (float(val) % 1) > 0:
                    amount_total = round(val) + 0.5
                else:
                    amount_total = 0
                if order.amount_tax and amount_total:
                    amount_round_off = amount_total - order.amount_tax
                    order.update({
                        'amount_total': amount_untaxed + amount_total,
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