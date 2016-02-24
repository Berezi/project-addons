# -*- coding: utf-8 -*-
# (c) 2016 Alfredo de la Fuente - AvanzOSC
# License AGPL-3 - See http://www.gnu.org/licenses/agpl-3.0.html
from openerp import models, api, fields, _
from datetime import datetime
from dateutil.relativedelta import relativedelta
import pytz


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    project_by_task = fields.Selection(
        [('yes', 'Yes'),
         ('no', 'No')], string='Create project by task')

    @api.multi
    def action_button_confirm(self):
        res = super(SaleOrder, self).action_button_confirm()
        self._create_event_and_sessions_from_sale_order()
        return res

    def _create_event_and_sessions_from_sale_order(self):
        event_obj = self.env['event.event']
        project_obj = self.env['project.project']
        account_obj = self.env['account.analytic.account']
        for sale in self:
            cond = [('analytic_account_id', '=', sale.project_id.id)]
            project = project_obj.search(cond, limit=1)
            event_vals = sale._prepare_event_data(project)
            event = event_obj.with_context(
                sale_order_create_event=True).create(event_vals)
            sale_lines = sale.order_line.filtered(
                lambda x: x.recurring_service)
            for line in sale_lines:
                num_session = 0
                sale._validate_create_session_from_sale_order(
                    event, num_session, line)
            if sale.project_by_task == 'yes':
                cond = [('parent_id', '=', sale.project_id.id)]
                accounts = account_obj.search(cond)
                cond = [('analytic_account_id', 'in', accounts.ids)]
                projects = project_obj.search(cond)
                projects.write({'event_id': event.id})

    def _prepare_event_data(self, project):
        event_vals = ({'name': self.name,
                       'timezone_of_event': self.env.user.tz,
                       'date_tz': self.env.user.tz,
                       'project_id': project.id})
        utc_dt = self._put_utc_format_date(self.project_id.date_start, 0)
        event_vals['date_begin'] = utc_dt
        utc_dt = self._put_utc_format_date(self.project_id.date, 0)
        event_vals['date_end'] = utc_dt
        return event_vals

    def _validate_create_session_from_sale_order(
            self, event, num_session, line):
        task_obj = self.env['project.task']
        fec_ini = fields.Datetime.from_string(
            self.project_id.date_start).date()
        if fec_ini.day != 1:
            while fec_ini.day != 1:
                fec_ini = fec_ini + relativedelta(days=-1)
        if fec_ini.weekday() == 0:
            num_week = 0
        else:
            num_week = 1
        month = fec_ini.month
        while (fec_ini <=
               fields.Datetime.from_string(self.project_id.date).date()):
            if month != fec_ini.month:
                month = fec_ini.month
                if fec_ini.weekday() == 0:
                    num_week = 0
                else:
                    num_week = 1
            if fec_ini.weekday() == 0:
                num_week += 1
            if fec_ini >= fields.Datetime.from_string(
                    self.project_id.date_start).date():
                valid = task_obj._validate_event_session_month(line, fec_ini)
                if valid:
                    valid = task_obj._validate_event_session_week(
                        line, num_week)
                if valid:
                    valid = task_obj._validate_event_session_day(line, fec_ini)
                if valid:
                    num_session += 1
                    self._create_session_from_sale_line(
                        event, num_session, line, fec_ini)
            fec_ini = fec_ini + relativedelta(days=+1)

    def _create_session_from_sale_line(
            self, event, num_session, line, date):
        vals = self._prepare_session_data_from_sale_line(
            event, num_session, line, date)
        session = self.env['event.track'].create(vals)
        session.tasks = [(4, line.service_project_task.id)]
        duration = sum(line.service_project_task.sessions.mapped('duration'))
        line.service_project_task.planned_hours = duration

    def _prepare_session_data_from_sale_line(
            self, event, num_session, line, date):
        if line.performance:
            duration = (line.performance * line.product_uom_qty)
        else:
            duration = line.product_uom_qty
        utc_dt = self._put_utc_format_date(date, 0)
        vals = {'name': (_('Session %s for %s') % (str(num_session),
                                                   line.product_id.name)),
                'event_id': event.id,
                'date': utc_dt,
                'duration': duration}
        return vals

    def _put_utc_format_date(self, date, time):
        new_date = (datetime.strptime(str(date), '%Y-%m-%d') +
                    relativedelta(hours=float(time)))
        local = pytz.timezone(self.env.user.tz)
        local_dt = local.localize(new_date, is_dst=None)
        utc_dt = local_dt.astimezone(pytz.utc)
        return utc_dt