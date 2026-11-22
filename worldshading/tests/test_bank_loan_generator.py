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

    def test_installment_amount_keeps_exact_cash_and_reconciles_principal(self):
        source=loan(annual_interest_rate=9)
        original=copy.deepcopy(source)
        result=self.generate(source,options(method='Equal Installments',calculation_mode='Installment Amount',installment_amount=1060))
        self.assertEqual(source,original)
        self.assertTrue(all(r['total_amount']==Decimal('1060.000') for r in result['rows']))
        self.assertEqual(result['scheduled_principal'],Decimal('12000.000'))
        self.assertEqual(result['scheduled_interest'],Decimal('720.000'))
        self.assertEqual(result['rows'][-1]['projected_principal_balance'],0)
        self.assertGreater(result['estimated_annual_rate'],Decimal('6'))
        self.assertEqual(result['installment_amount'],Decimal('1060.000'))
        self.assertEqual(result['final_payment_adjustment'],0)
        self.assertIn('estimated nominal annual rate',result['rows'][0]['remarks'])

    def test_installment_amount_matches_known_flat_rate_and_existing_opening(self):
        result=self.generate(loan(interest_calculation_basis='Flat Rate'),options(method='Equal Installments',calculation_mode='Installment Amount',installment_amount=1060))
        self.assertEqual(result['estimated_annual_rate'],Decimal('6'))
        self.assertEqual(result['scheduled_interest'],Decimal('720.000'))
        existing=loan(loan_position='Existing Loan',original_principal=24000,interest_calculation_basis='Flat Rate')
        result=self.generate(existing,options(method='Equal Installments',calculation_mode='Installment Amount',installment_amount=1060))
        self.assertEqual(result['estimated_annual_rate'],Decimal('3'))
        self.assertEqual(result['scheduled_principal'],Decimal('12000.000'))

    def test_installment_amount_zero_rate_and_small_final_rounding_are_explicit(self):
        result=self.generate(settings=options(method='Equal Installments',calculation_mode='Installment Amount',installment_amount=1000))
        self.assertEqual(result['estimated_annual_rate'],0)
        self.assertEqual(result['scheduled_interest'],0)
        source=loan(original_principal=100,opening_principal=100)
        result=self.generate(source,options(method='Equal Installments',calculation_mode='Installment Amount',installment_amount='33.333',periods=3))
        self.assertEqual(result['estimated_annual_rate'],0)
        self.assertEqual(result['rows'][-1]['total_amount'],Decimal('33.334'))
        self.assertEqual(result['final_payment_adjustment'],Decimal('0.001'))

    def test_installment_amount_rejects_bad_combinations_and_underfunded_payments(self):
        base=options(method='Equal Installments',calculation_mode='Installment Amount',installment_amount=1060)
        for value in [None,0,-1,'NaN','Infinity','1e100000000',900]:
            with self.subTest(amount=value),self.assertRaises(ValueError):
                self.generate(settings=dict(base,installment_amount=value))
        for settings in [dict(base,method='Equal Principal'),dict(base,rate_change=1),dict(base,calculation_mode='bad')]:
            with self.subTest(settings=settings),self.assertRaises(ValueError):self.generate(settings=settings)
        with self.assertRaises(ValueError):self.generate(loan(interest_rate_type='Variable'),base)

    def test_installment_amount_diminishing_rate_matches_independent_two_period_example(self):
        # 1210 / 1.1 + 1210 / 1.1**2 = 2100, so periodic rate is exactly 10%.
        result=self.generate(loan(original_principal=2100,opening_principal=2100),
            options(method='Equal Installments',calculation_mode='Installment Amount',installment_amount=1210,periods=2))
        self.assertEqual(result['estimated_annual_rate'],Decimal('120.000000'))
        self.assertEqual([r['interest_amount'] for r in result['rows']],[Decimal('210.000'),Decimal('110.000')])
        self.assertEqual(result['scheduled_interest'],Decimal('320.000'))

    def test_installment_amount_bounds_precision_and_historical_rows(self):
        base=options(method='Equal Installments',calculation_mode='Installment Amount',installment_amount=1060)
        for periods in [0,601,'1e100000000']:
            with self.subTest(periods=periods),self.assertRaises(ValueError):
                self.generate(settings=dict(base,periods=periods))
        source=loan(schedule=self.generate()['rows'])
        with self.assertRaises(ValueError):self.generate(source,base,today='2027-01-01')
        source=loan(maturity_date='2076-11-19')
        result=self.generate(source,dict(base,periods=600,installment_amount=100))
        self.assertEqual(len(result['rows']),600)
        self.assertEqual(result['scheduled_principal'],12000)
        self.assertEqual(result['scheduled_total'],60000)
        self.assertTrue(all(r['total_amount']==100 for r in result['rows']))
        source=loan(original_principal='0.01',opening_principal='0.01')
        with self.assertRaises(ValueError):self.generate(source,dict(base,installment_amount='0.01'))

    def test_installment_amount_rejects_material_rounding_and_unrepresentable_rate(self):
        base=options(method='Equal Installments',calculation_mode='Installment Amount')
        source=loan(maturity_date='2036-11-19')
        with self.assertRaises(ValueError):self.generate(source,dict(base,periods=100,installment_amount='1200.087'))
        source=loan(original_principal=1000,opening_principal=1000)
        with self.assertRaises(ValueError):self.generate(source,dict(base,periods=1,installment_amount='1e22'))

    def test_installment_amount_single_payment_and_quarterly_period(self):
        result=self.generate(settings=options(method='Equal Installments',calculation_mode='Installment Amount',installment_amount=12600,periods=1))
        self.assertEqual(result['estimated_annual_rate'],Decimal('60'))
        self.assertEqual(result['scheduled_interest'],600)
        result=self.generate(loan(repayment_frequency='Quarterly',interest_calculation_basis='Flat Rate'),
            options(method='Equal Installments',calculation_mode='Installment Amount',installment_amount=3180,periods=4))
        self.assertEqual(result['estimated_annual_rate'],Decimal('6'))
        self.assertTrue(all(r['total_amount']==3180 for r in result['rows']))

    def recorded(self, source=None, **settings):
        values=options(method='Equal Installments',calculation_mode='Installment Amount',
            rate_source='Use Recorded Rate',installment_amount=1000)
        values.update(settings)
        return self.generate(source or loan(annual_interest_rate=0),values)

    def test_recorded_zero_rate_lowers_final_payment_and_stops_early(self):
        source=loan(original_principal='322355.595',opening_principal='272347.595',loan_position='Existing Loan',
            annual_interest_rate=0,maturity_date='2040-01-19',interest_calculation_basis='Flat Rate')
        result=self.recorded(source,installment_amount=1786,periods=153)
        self.assertEqual(len(result['rows']),153)
        self.assertTrue(all(r['total_amount']==1786 for r in result['rows'][:152]))
        self.assertEqual(result['rows'][-1]['total_amount'],Decimal('875.595'))
        self.assertEqual(result['scheduled_principal'],Decimal('272347.595'))
        self.assertEqual(result['scheduled_interest'],0)
        self.assertNotIn('estimated_annual_rate',result)
        self.assertEqual(result['recorded_annual_rate'],0)
        self.assertEqual(result['rows'][-1]['projected_principal_balance'],0)
        early=self.recorded(loan(annual_interest_rate=0),installment_amount=5000)
        self.assertEqual([r['total_amount'] for r in early['rows']],[5000,5000,2000])

    def test_recorded_residual_adds_settlement_or_adjusts_last_and_extends_maturity(self):
        source=loan(annual_interest_rate=0,maturity_date='2026-12-19')
        added=self.recorded(source,installment_amount=5000,periods=1)
        self.assertEqual([r['total_amount'] for r in added['rows']],[5000,7000])
        self.assertTrue(added['settlement_added'])
        self.assertTrue(added['rows'][-1]['settlement_row'])
        self.assertEqual(added['maturity_date'],'2027-01-19')
        self.assertEqual(added['previous_maturity_date'],'2026-12-19')
        last=self.recorded(source,installment_amount=5000,periods=1,remaining_balance='Add to Last Installment')
        self.assertEqual(len(last['rows']),1)
        self.assertEqual(last['rows'][0]['total_amount'],12000)
        self.assertFalse(last['settlement_added'])
        self.assertNotIn('maturity_date',last)

    def test_recorded_settlement_preserves_month_end_anchor(self):
        result=self.recorded(loan(annual_interest_rate=0,maturity_date='2027-02-28'),
            installment_amount=1000,periods=2,first_due_date='2027-01-31')
        self.assertEqual([r['due_date'] for r in result['rows']],
            ['2027-01-31','2027-02-28','2027-03-31'])
        self.assertEqual(result['maturity_date'],'2027-03-31')
        self.assertEqual(result['scheduled_principal'],12000)

    def test_recorded_zero_interest_rounding_does_not_add_an_extra_period(self):
        source=loan(annual_interest_rate=0,original_principal=100,opening_principal=100)
        result=self.recorded(source,installment_amount='33.333',periods=3)
        self.assertEqual(len(result['rows']),3)
        self.assertEqual(result['rows'][-1]['total_amount'],Decimal('33.334'))
        self.assertEqual(result['scheduled_interest'],0)
        self.assertFalse(result['settlement_added'])

    def test_recorded_rate_uses_actual_rate_and_interest_on_extra_settlement_period(self):
        source=loan(annual_interest_rate=6)
        result=self.recorded(source,installment_amount=1000,periods=1)
        self.assertEqual(result['rows'][0]['interest_amount'],60)
        self.assertEqual(result['rows'][0]['principal_amount'],940)
        self.assertEqual(result['rows'][1]['principal_amount'],11060)
        self.assertEqual(result['rows'][1]['interest_amount'],Decimal('55.300'))
        self.assertEqual(result['recorded_annual_rate'],6)
        self.assertEqual(source['annual_interest_rate'],6)
        adjusted=self.recorded(source,installment_amount=1000,periods=1,remaining_balance='Add to Last Installment')
        self.assertEqual(adjusted['scheduled_total'],12060)
        self.assertEqual(adjusted['scheduled_interest'],60)

    def test_recorded_interest_only_regular_payments_are_allowed_but_negative_amortisation_is_not(self):
        result=self.recorded(loan(annual_interest_rate=6),installment_amount=60,periods=2)
        self.assertEqual([r['principal_amount'] for r in result['rows']],[0,0,12000])
        self.assertEqual(result['scheduled_interest'],180)
        with self.assertRaises(ValueError):self.recorded(loan(annual_interest_rate=6),installment_amount=59,periods=2)

    def test_recorded_rate_mode_rejects_invalid_options_and_retains_limits(self):
        for fields in [dict(rate_source='bad'),dict(remaining_balance='bad')]:
            with self.assertRaises(ValueError):self.recorded(**fields)
        with self.assertRaises(ValueError):self.recorded(loan(interest_rate_type='Variable',annual_interest_rate=0))
        source=loan(annual_interest_rate=0,maturity_date='2076-11-19')
        with self.assertRaises(ValueError):self.recorded(source,installment_amount=1,periods=600)
        result=self.recorded(source,installment_amount=1,periods=600,remaining_balance='Add to Last Installment')
        self.assertEqual(len(result['rows']),600)
        self.assertEqual(result['scheduled_principal'],12000)
        other=self.recorded(loan(annual_interest_rate=0,interest_calculation_basis='Bank Schedule / Other'))
        self.assertEqual(other['scheduled_interest'],0)

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
