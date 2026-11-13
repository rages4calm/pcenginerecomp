"""Conservative N/Z/V facts and explicit conditional candidate decisions.

This module never changes emitted branch operations. Facts are A/X/Y/C/D/T/N/Z/V;
unknown memory/status stays unknown. Conditions refine only their tested bit.
"""
FLAGS = ('c', 'd', 't', 'n', 'z', 'v')
CONDITIONS = {'BCC':('c',0),'BCS':('c',1),'BNE':('z',0),'BEQ':('z',1),
              'BPL':('n',0),'BMI':('n',1),'BVC':('v',0),'BVS':('v',1)}


def extend_status(ins, incoming, outgoing, operand=None):
    """Append N/Z/V to an already evaluated six-component register result."""
    name=ins.mnemonic
    n,z,v=incoming[6:]
    value=None
    changes_nz=False
    if ins.mode=='imm':operand=ins.data[1]
    if name in ('PLP','RTI','ILL'):
        n=z=v=None
    elif name=='CLV':v=0
    elif name in ('BIT','TST','TSB','TRB'):
        # Memory/test effects are not guessed; even register-preserving test
        # instructions can replace N/V on this CPU.
        n=z=v=None
    elif name in ('CMP','CPX','CPY'):
        left=incoming[('CMP','CPX','CPY').index(name)]
        value=None if left is None or operand is None else (left-operand)&255
        changes_nz=True
    elif name in ('ADC','SBC','AND','ORA','EOR'):
        routed=name!='SBC' and incoming[5]!=0
        value=None if routed else outgoing[0]
        changes_nz=True
        if name in ('ADC','SBC'):
            decimal=incoming[4]
            if decimal!=1:
                left=incoming[0]
                if decimal is None or routed or left is None or operand is None or value is None:v=None
                else:v=int(bool((left^value)&((left^operand) if name=='SBC' else ~(left^operand))&128))
    elif name in ('LDA','LDX','LDY','TAX','TAY','TXA','TYA','INA','DEA','INX','DEX','INY','DEY'):
        value=outgoing[('a','x','y').index(name[-1].lower())];changes_nz=True
    elif name in ('ASL','LSR','ROL','ROR','INC','DEC'):
        value=outgoing[0] if ins.mode=='acc' else None;changes_nz=True
    elif name in ('PLA','PLX','PLY','TSX'):
        changes_nz=True
    if changes_nz:
        n=None if value is None else int(value>=128)
        z=None if value is None else int(value==0)
    return (*outgoing,n,z,v)


def flag_decision(name,facts):
    flag,expected=CONDITIONS[name]
    value=facts[3+FLAGS.index(flag)]
    return dict(flag=flag,expected=expected,value=value,
                decision='both' if value is None else 'taken' if value==expected else 'fallthrough')


def refine(facts,record,kind):
    """Unknown flag edges can supply one tested bit; bit branches do not."""
    if 'flag' not in record:return facts
    values=list(facts);values[3+FLAGS.index(record['flag'])]=record['expected'] if kind=='taken' else 1-record['expected']
    return tuple(values)
