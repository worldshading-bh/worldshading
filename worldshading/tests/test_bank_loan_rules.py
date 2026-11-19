"""Pure schedule tests: never initialize a Frappe site."""
import unittest
from decimal import Decimal
from worldshading.worldshading.doctype.bank_loan import rules


def loan(**changes):
    values = dict(original_principal=1000, opening_principal=600,
                  disbursement_date='2026-01-01', tracking_start_date='2026-11-01',
                  maturity_date='2027-01-31', annual_interest_rate=6,
                  schedule=[dict(due_date='2026-11-30', principal_amount='256.334',
                                 interest_amount='53.666', charges_amount=0),
                            dict(due_date='2026-12-31', principal_amount='343.666',
                                 interest_amount='20', charges_amount='1')])
    values.update(changes)
    return values


class BankLoanRulesTests(unittest.TestCase):
    def test_existing_loan_uses_opening_not_original_principal(self):
        result = rules.calculate_schedule(loan(), 3, complete=True)
        self.assertEqual(result['rows'][0]['total_amount'], Decimal('310.000'))
        self.assertEqual(result['rows'][0]['projected_principal_balance'], Decimal('343.666'))
        self.assertEqual(result['rows'][1]['projected_principal_balance'], Decimal('0.000'))
        self.assertEqual(result['scheduled_principal'], Decimal('600.000'))
        self.assertEqual(result['scheduled_interest'], Decimal('73.666'))
        self.assertEqual(result['scheduled_total'], Decimal('674.666'))
        self.assertEqual(set(result), {'rows', 'original_principal', 'opening_principal',
            'scheduled_principal', 'scheduled_interest', 'scheduled_charges',
            'scheduled_total', 'unscheduled_principal'})

    def test_incomplete_schedule_saved_in_draft_but_not_activated(self):
        rules.calculate_schedule(loan(schedule=[]), 3)
        with self.assertRaises(ValueError):
            rules.calculate_schedule(loan(schedule=[]), 3, complete=True)
        with self.assertRaises(ValueError):
            rules.calculate_schedule(loan(schedule=loan()['schedule'][:1]), 3, complete=True)

    def test_new_loan_requires_original_opening_position(self):
        for changes in [dict(loan_position='New Loan'),
                        dict(loan_position='New Loan', opening_principal=1000)]:
            with self.assertRaises(ValueError):
                rules.calculate_schedule(loan(**changes), 3)
        result = rules.calculate_schedule(loan(loan_position='New Loan', opening_principal=1000,
            tracking_start_date='2026-01-01'), 3)
        self.assertEqual(result['opening_principal'], Decimal('1000.000'))

    def test_revision_can_extend_maturity_but_new_schedule_cannot_silently_extend(self):
        values=loan(workflow_state='Draft',approved_plan='{}')
        values['schedule'][-1]['due_date']='2027-02-05'
        result=rules.calculate_schedule(values,3,complete=True)
        self.assertEqual(result['maturity_date'],'2027-02-05')
        values.pop('approved_plan')
        with self.assertRaises(ValueError):rules.calculate_schedule(values,3)
        values['approved_plan']='{}'
        values['schedule'][-1]['due_date']=values['schedule'][0]['due_date']
        with self.assertRaises(ValueError):rules.calculate_schedule(values,3)

    def test_invalid_opening_and_rate(self):
        for changes in [dict(opening_principal=1001), dict(opening_principal=0),
                        dict(original_principal=-1), dict(annual_interest_rate=-1),
                        dict(opening_principal='NaN'), dict(annual_interest_rate='Infinity')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                rules.calculate_schedule(loan(**changes), 3)

    def test_invalid_schedule_amounts(self):
        for field, value in [('principal_amount', -1), ('interest_amount', 'NaN'),
                             ('charges_amount', 'Infinity'), ('principal_amount', 601)]:
            row = dict(loan()['schedule'][0], **{field: value})
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                rules.calculate_schedule(loan(schedule=[row]), 3)
        with self.assertRaises(ValueError):
            rules.calculate_schedule(loan(schedule=[dict(due_date='2026-11-30')]), 3)

    def test_dates_must_be_ordered_unique_and_in_tracking_period(self):
        for dates in [('2026-11-30', '2026-11-30'), ('2026-12-31', '2026-11-30'),
                      ('2026-10-31', '2026-11-30'), ('2026-11-30', '2027-02-01')]:
            rows = [dict(due_date=d, principal_amount=300) for d in dates]
            with self.subTest(dates=dates), self.assertRaises(ValueError):
                rules.calculate_schedule(loan(schedule=rows), 3)
        for changes in [dict(tracking_start_date='2025-01-01'), dict(maturity_date='2026-10-01')]:
            with self.assertRaises(ValueError):
                rules.calculate_schedule(loan(**changes), 3)

    def test_currency_rounding_and_interest_only_installment(self):
        rows = [dict(due_date='2026-11-30', principal_amount=0, interest_amount='1.005'),
                dict(due_date='2026-12-31', principal_amount=600)]
        result = rules.calculate_schedule(loan(schedule=rows), 2, complete=True)
        self.assertEqual(result['rows'][0]['total_amount'], Decimal('1.01'))
        self.assertEqual(result['rows'][0]['interest_amount'], Decimal('1.01'))
        self.assertEqual(result['rows'][0]['projected_principal_balance'], Decimal('600.00'))
        self.assertEqual(result['scheduled_total'], Decimal('601.01'))


if __name__ == '__main__':
    unittest.main()
