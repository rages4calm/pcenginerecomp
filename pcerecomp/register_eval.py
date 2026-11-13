"""Bounded abstract register operations, never guest execution or code folding.

Facts are A/X/Y/C/D/T, each a byte/bit or None. Decimal inference is deliberately
limited to valid BCD operands; unsupported facts stay unknown. No writable
memory or status stack is predicted. This implementation uses integer/decimal
arithmetic, not reference-emulator code.
"""
from .analysis import _register_facts

ALU = frozenset(('ADC', 'SBC', 'AND', 'ORA', 'EOR', 'CMP', 'CPX', 'CPY'))
NAMES = ('a', 'x', 'y', 'c', 'd', 't')


def evaluate(ins, facts, mpr, operand=None):
    """Return conservative outgoing facts and an optional loss-of-fact reason."""
    a, x, y, carry, decimal, transfer = facts
    registers = list(_register_facts(ins, facts[:3], mpr))
    name = ins.mnemonic
    next_c, next_d, next_t = carry, decimal, int(name == 'SET')
    reason = None
    if name in ('PLP', 'RTI'):
        next_c = next_d = next_t = None
        reason = 'status_restore_unknown'
    elif name in ('CLC', 'SEC'):
        next_c = int(name == 'SEC')
    elif name in ('CLD', 'SED', 'BRK'):
        next_d = int(name == 'SED')
    if name in ALU:
        if ins.mode == 'imm':
            operand = ins.data[1]
        if name in ('CMP', 'CPX', 'CPY'):
            left = {'CMP': a, 'CPX': x, 'CPY': y}[name]
            next_c = None if left is None or operand is None else int(left >= operand)
            if next_c is None:
                reason = 'comparison_unknown'
        elif name != 'SBC' and transfer != 0:
            # SET-routed operations write untracked direct-page memory, not A.
            # Unknown T joins both possibilities; do not guess its destination.
            registers[0] = a if transfer == 1 else None
            if name == 'ADC':
                next_c = None
            reason = 'transfer_destination_untracked' if transfer == 1 else 'unknown_transfer'
        elif a is None or operand is None:
            registers[0] = None
            if name in ('ADC', 'SBC'):
                next_c = None
            reason = 'unknown_accumulator' if a is None else 'unknown_operand'
        elif name in ('AND', 'ORA', 'EOR'):
            registers[0] = a & operand if name == 'AND' else a | operand if name == 'ORA' else a ^ operand
        elif carry is None or decimal is None:
            registers[0] = next_c = None
            reason = 'unknown_carry' if carry is None else 'unknown_decimal'
        elif decimal and any((v & 15) > 9 or (v >> 4) > 9 for v in (a, operand)):
            registers[0] = next_c = None
            reason = 'invalid_bcd_operand'
        else:
            left, right = a, operand
            if decimal:
                left, right = (a >> 4)*10 + (a & 15), (operand >> 4)*10 + (operand & 15)
            value = left + right + carry if name == 'ADC' else left - right - (1-carry)
            next_c = int(value >= (100 if decimal else 256)) if name == 'ADC' else int(value >= 0)
            registers[0] = ((value % 100 // 10) << 4) | (value % 10) if decimal else value & 255
    elif name in ('ASL', 'LSR', 'ROL', 'ROR'):
        next_c = None
        if ins.mode == 'acc':
            next_c = None if a is None else (a >> 7 if name in ('ASL', 'ROL') else a & 1)
            if a is None or name in ('ROL', 'ROR') and carry is None:
                registers[0] = None
                reason = 'unknown_accumulator' if a is None else 'unknown_carry'
            else:
                registers[0] = {'ASL': a << 1, 'LSR': a >> 1,
                    'ROL': (a << 1) | (carry or 0), 'ROR': (a >> 1) | ((carry or 0) << 7)}[name] & 255
        else:
            reason = 'memory_shift_carry_unknown'
    return (*registers, next_c, next_d, next_t), reason
