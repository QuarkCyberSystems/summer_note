# -*- coding: utf-8 -*-
# Copyright (c) 2023, QCS and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe.model.document import Document

class BrandwiseSalesTeamContribution(Document):
	def before_save(self, method=None):
		if (self.total_contribution != 100 and self.total_contribution > 0):
			 frappe.throw("Error: Incomplete contribution allocation.")
