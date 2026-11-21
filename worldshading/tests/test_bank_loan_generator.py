"""Pure Decimal generation checks; no Frappe site or accounting writes."""
import copy
import unittest
from unittest.mock import patch
from decimal import Decimal
from worldshading.worldshading.doctype.bank_loan.generator import generate_schedule


def loan(**values):
    d = dict(original_principal=12000, opening_principal=12000, annual_interest_rate=6,
        disbursement_date='2026-11-19', tracking_start_date='2026-11-19',
        maturity_date='2027-11-19', repayment_frequency='Monthly',
        loan_position='New Loan', interest_calculation_basis='Diminishing',
        interest_rate_type='Fixed', schedule=[])
    d.update(values)
    return d


def options(**values):
    d = dict(method='Equal Principal', first_due_date='2026-12-19', periods=12)
    d.update(values)
    return d


class TestBankLoanGenerator(unittest.TestCase):
    def generate(self, source=None, settings=None, today='2026-11-19', precision=3):
        return generate_schedule(source or loan(), settings or options(), precision, today)

    def test_equal_principal_and_flat_are_distinct(self):
        dim = self.generate()
        self.assertEqual(dim['scheduled_interest'], Decimal('390.000'))
        self.assertEqual(dim['rows'][0]['total_amount'], Decimal('1060.000'))
        self.assertEqual(dim['rows'][-1]['total_amount'], Decimal('1005.000'))
        flat = self.generate(loan(interest_calculation_basis='Flat Rate'))
        self.assertEqual(flat['scheduled_interest'], Decimal('720.000'))
        self.assertTrue(all(r['total_amount'] == Decimal('1060.000') for r in flat['rows']))

    def test_equal_installments_reconcile_rounding_in_last_payment(self):
        result = self.generate(settings=options(method='Equal Installments'))
        self.assertEqual(result['scheduled_interest'], Decimal('393.566'))
        self.assertEqual(result['rows'][0]['total_amount'], Decimal('1032.797'))
        self.assertEqual(result['rows'][-1]['total_amount'], Decimal('1032.799'))
        self.assertEqual(sum(r['principal_amount'] for r in result['rows']), Decimal('12000.000'))
        self.assertEqual(result['rows'][-1]['projected_principal_balance'], Decimal('0.000'))

    def test_zero_rate_and_balloon(self):
        zero = self.generate(loan(annual_interest_rate=0), options(method='Equal Installments'))
        self.assertEqual(zero['scheduled_interest'], 0)
        self.assertTrue(all(r['total_amount'] == 1000 for r in zero['rows']))
        balloon = self.generate(settings=options(method='Interest Only / Balloon'))
        self.assertEqual(balloon['rows'][0]['principal_amount'], 0)
        self.assertEqual(balloon['rows'][0]['total_amount'], 60)
        self.assertEqual(balloon['rows'][-1]['total_amount'], 12060)

    def test_existing_flat_uses_original_principal_for_interest(self):
        result = self.generate(loan(loan_position='Existing Loan', original_principal=24000,
                                   interest_calculation_basis='Flat Rate'))
        self.assertEqual(result['rows'][0]['interest_amount'], 120)
        self.assertEqual(result['scheduled_principal'], 12000)

    def test_anchor_does_not_drift_at_month_end(self):
        result = self.generate(loan(maturity_date='2027-03-31'),
            options(first_due_date='2027-01-31', periods=3))
        self.assertEqual([r['due_date'] for r in result['rows']], ['2027-01-31','2027-02-28','2027-03-31'])
        quarterly = self.generate(loan(repayment_frequency='Quarterly'), options(periods=4))
        self.assertEqual([r['due_date'] for r in quarterly['rows']],
            ['2026-12-19','2027-03-19','2027-06-19','2027-09-19'])
        self.assertEqual(quarterly['rows'][0]['interest_amount'], 180)

    def test_invalid_inputs_and_maturity(self):
        for settings in [options(periods=0), options(periods=601), options(periods=1.5),
                         options(periods='NaN'), options(method='bad'), options(first_due_date='2026-01-01')]:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.generate(settings=settings)
        for source in [loan(annual_interest_rate=-1), loan(annual_interest_rate='Infinity'),
                       loan(opening_principal=0), loan(repayment_frequency='Custom'),
                       loan(interest_calculation_basis='Bank Schedule / Other'), loan(maturity_date='2026-12-18')]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.generate(source)
        with self.assertRaises(ValueError):
            self.generate(loan(original_principal='.01', opening_principal='.01'), precision=2)

    def test_historical_rows_are_not_replaced_by_full_generation(self):
        source = loan(schedule=self.generate()['rows'])
        with self.assertRaises(ValueError):
            self.generate(source, today='2027-01-01')

    def test_variable_loan_generates_without_review_checkbox(self):
        result = self.generate(loan(interest_rate_type='Variable'))
        self.assertEqual(result['scheduled_interest'], Decimal('390.000'))

    def test_future_rate_change_preserves_prefix_and_uses_remaining_principal(self):
        source = loan(interest_rate_type='Variable', schedule=self.generate()['rows'])
        original = copy.deepcopy(source)
        result = self.generate(source, options(rate_change=1, effective_date='2027-06-19',
            new_rate=9), today='2027-01-01')
        self.assertEqual(source, original)
        self.assertEqual(result['retained_rows'], 6)
        self.assertEqual(result['rows'][:6], source['schedule'][:6])
        self.assertEqual(result['rows'][6]['interest_amount'], 45)
        self.assertEqual(result['scheduled_interest'], Decimal('442.500'))
        self.assertEqual(result['rows'][-1]['projected_principal_balance'], 0)

    def test_future_rate_change_keeps_existing_fees(self):
        source = loan(interest_rate_type='Variable', schedule=self.generate()['rows'])
        source['schedule'][6]['charges_amount'] = Decimal('10.000')
        source['schedule'][6]['remarks'] = 'Bank fee to retain'
        result = self.generate(source, options(rate_change=1,effective_date='2027-06-19',
            new_rate=9))
        self.assertEqual(result['rows'][6]['charges_amount'], 10)
        self.assertIn('Bank fee to retain', result['rows'][6]['remarks'])
        self.assertEqual(result['scheduled_total'], Decimal('12452.500'))
        with self.assertRaises(ValueError):
            self.generate(source, options(rate_change=1,effective_date='2027-06-01',
                new_rate=9))

    def test_rate_update_rejects_irregular_bank_dates(self):
        source = loan(interest_rate_type='Variable', schedule=[
            dict(due_date='2026-12-19',principal_amount=6000,interest_amount=60),
            dict(due_date='2027-11-19',principal_amount=6000,interest_amount=30)])
        with self.assertRaises(ValueError):
            self.generate(source, options(rate_change=1,effective_date='2026-12-19',new_rate=9))

    def test_out_of_range_count_is_rejected_before_integer_expansion(self):
        with patch('worldshading.worldshading.doctype.bank_loan.generator.int',
                   side_effect=AssertionError('Rejected count must not be expanded'),create=True):
            with self.assertRaises(ValueError):
                self.generate(settings=options(periods='1e100000000'))

    def test_rate_change_rejects_past_or_incomplete_schedule(self):
        source = loan(interest_rate_type='Variable', schedule=self.generate()['rows'])
        for settings in [options(rate_change=1, effective_date='2026-11-01',new_rate=9),
                         options(rate_change=1, effective_date='2028-01-01',new_rate=9)]:
            with self.assertRaises(ValueError):
                self.generate(source, settings)
        source['schedule'] = source['schedule'][:2]
        with self.assertRaises(ValueError):
            self.generate(source, options(rate_change=1,effective_date='2027-01-19',new_rate=9))


if __name__ == '__main__': unittest.main()
