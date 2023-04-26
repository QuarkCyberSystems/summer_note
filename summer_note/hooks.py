# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from . import __version__ as app_version

app_name = "summer_note"
app_title = "Summer Note"
app_publisher = "QCS"
app_description = "restore note"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "vivek@quarkcs.com"
app_license = "MIT"

# Includes in <head>
# ------------------

app_include_js = [

"assets/js/summernote.min.js",

"assets/js/editor.min.js"


]

app_include_css = [

"assets/css/summernote.min.css"
]



# include js, css files in header of desk.html
# app_include_css = "/assets/summer_note/css/summer_note.css"
# app_include_js = "/assets/summer_note/js/summer_note.js"

# include js, css files in header of web template
# web_include_css = "/assets/summer_note/css/summer_note.css"
# web_include_js = "/assets/summer_note/js/summer_note.js"

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Website user home page (by function)
# get_website_user_home_page = "summer_note.utils.get_home_page"

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Installation
# ------------

# before_install = "summer_note.install.before_install"
# after_install = "summer_note.install.after_install"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "summer_note.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
#	}
# }

#doc_events = {
 #   "Timesheet": {
#        "on_submit": "summer_note.common.ot_timesheet"
#    },
#    "Sales Order": {
#        "before_submit": "summer_note.common.add_project"
#    },
#    "Salary Slip": {
#        "before_save": "summer_note.common.add_expense_claim",
#        "on_submit": ["summer_note.common.add_benefits", "summer_note.common.allocate_leave"],
#        "on_cancel": "summer_note.common.cancel_salary_slip"
#    },
#    "Leave Application": {
#        "on_submit": "summer_note.common.add_dues",
#        "on_cancel": "summer_note.common.cancel_dues"
#    }

#}

doc_events = {
	"Timesheet": {
		"on_submit": "summer_note.common.ot_timesheet", #1/13
		"on_cancel": "summer_note.common.cancel_timesheet" #11/13
	},
	"Leave Application": {
		"on_cancel": "summer_note.common.cancel_dues" #2/13
	},
	"Salary Slip": {
		"after_insert": ["summer_note.common.add_expense_claim", "summer_note.common.add_benefits", 
		"summer_note.common.add_dues", "summer_note.common.allocate_leave"], #3/13, #4/13, 5/13, 6/13
		#"on_submit":  "summer_note.common.allocate_leave", # 6/13
		"on_cancel": "summer_note.common.cancel_salary_slip", #7/13
		"on_trash": "summer_note.common.cancel_salary_slip" #7/13
		},
	"Expense Claim": {
		"on_cancel": "summer_note.common.cancel_expense_claim" #10/13
	},
	"Purchase Receipt": {
		#"validate": "summer_note.common.correct_discount_amount",
		"before_submit": "summer_note.common.pull_po_number" #10/13
	},	
	"Sales Order": {
		#"before_submit": "summer_note.common.add_project" #8/13
		"on_submit": "summer_note.common.auto_reserve_stock",
		"before_cancel": "summer_note.common.cancel_reserved_qty",
        "on_cancel":"summer_note.common.cancel_reservation"
	},
	"Payroll Entry": {
		"before_cancel": "summer_note.common.cancel_payroll_entry", #12/13
		# "on_trash" : "summer_note.common.delete_payroll_entry" #7/13
	},
	"Delivery Note": {
		"validate":"summer_note.common.confirm_partial_delivery_allowed",
		"before_update_after_submit": "summer_note.common.set_dn_status",
		"on_update": "summer_note.common.set_dn_status",
		"after_insert": "summer_note.common.set_dn_status", 
		"on_cancel": "summer_note.common.cancel_dn_nest_status",
		"before_submit": "summer_note.common.set_dn_status",
		"on_submit": "summer_note.common.set_dn_status"
	},
	"Comment": {
		"before_insert":"summer_note.common.pad_comment_with_timestamp"
	},
	"Sales Invoice": {
		"on_update":"summer_note.common.update_dn_nest_status",
		"on_cancel":"summer_note.common.update_dn_nest_status",
		"before_update_after_submit":"summer_note.common.update_dn_nest_status"
		#"on_submit": "summer_note.common.update_dn_nest_status"
   },
}


# Scheduled Tasks
# ---------------

scheduler_events = {
# 	"all": [
# 		"summer_note.tasks.all"
# 	],
 	"daily": [
 		"summer_note.common.mark_absent", # 9/13
		"summer_note.common.expire_bank_guarantees",
		"summer_note.common.update_item_groups",
        "summer_note.common.send_leave_circular",
        "summer_note.common.create_stock_aging",
        "summer_note.common.make_bonus_accrual"
 	]   
# 	"hourly": [
# 		"summer_note.tasks.hourly"
# 	],
# 	"weekly": [
# 		"summer_note.tasks.weekly"
# 	]
# 	"monthly": [
# 		"summer_note.tasks.monthly"
# 	]
 }

# Testing
# -------

# before_tests = "summer_note.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "summer_note.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "summer_note.task.get_dashboard_data"
# }
#override_doctype_class = {
#	"BankGuarantee" : "summer_note.overrides.Nest_BankGuarantee",
#}
