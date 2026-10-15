import { describe, expect, it } from 'vitest';
import { money, topUpPresets, validateTopUp } from '@/lib/agentos/mockData';
describe('Wallet rules',()=>{
 it('offers the specified top-up presets',()=>{expect(topUpPresets).toEqual([20,50,100,250]);});
 it('formats rolled money to two decimals',()=>{expect(money(1284.5)).toBe('$1,284.50');});
 it('formats ledger micro amounts to four decimals',()=>{expect(money(.0024,4)).toBe('$0.0024');});
 it('rejects zero and negative top-ups',()=>{expect(validateTopUp(0)).toBe(false);expect(validateTopUp(-20)).toBe(false);expect(validateTopUp(50)).toBe(true);});
});
