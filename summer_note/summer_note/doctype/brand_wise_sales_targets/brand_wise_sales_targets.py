# -*- coding: utf-8 -*-
# Copyright (c) 2023, QCS and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document

class BrandwiseSalesTargets(Document):
	def on_update(self):
		create_contributions(self)

	def after_insert(self):
		create_contributions(self)
	
def create_contributions(self):
	sql = "select sti.brand brand, sti.type type , sti.region region " + \
	"from `tabBrand wise Child Table` sti  " + \
	"left join `tabBrand wise Sales Team Contribution` stc " + \
	"on sti.brand = stc.brand and sti.type = stc.type and sti.region = stc.region " + \
	"where sti.parent = '" + self.name + "' " + \
	"and stc.brand is null and stc.type is null and stc.region is null;"

	data = frappe.db.sql(sql, as_dict=1)

	if data and data[0]["brand"] is not None:
		for item in data:
			stc = frappe.new_doc("Brand wise Sales Team Contribution")
			stc.brand = item['brand']
			stc.type = item['type']
			stc.region = item['region']
			stc.save()

