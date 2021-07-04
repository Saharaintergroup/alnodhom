# -*- coding: utf-8 -*-
import math

from odoo import api, fields, models, _
from odoo.tools import float_round


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
            other_taxes_depends = 0
            val1 = 0
            val2 = 0
            if order.is_enabled_roundoff == True:
                for line in order.order_line:
                    for tax in line.taxes_id:
                        if tax.other_tax == True:
                            other_taxes_depends += (tax.depends_tax.amount / 100) * line.price_subtotal
                            other_taxes += (tax.amount / 100) * other_taxes_depends
                            val2 += float_round(other_taxes, precision_rounding=tax.rounding,
                                                rounding_method=tax.rounding_method)
                        else:
                            sales_taxes += (tax.amount / 100) * line.price_subtotal
                            val1 += float_round(sales_taxes, precision_rounding=tax.rounding,
                                                rounding_method=tax.rounding_method)

                total_taxes = val1 + val2
                if order.amount_tax and total_taxes:
                    amount_round_off = total_taxes - order.amount_tax
                    order.update({
                        'amount_total': amount_untaxed + total_taxes,
                        'amount_tax':total_taxes,
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