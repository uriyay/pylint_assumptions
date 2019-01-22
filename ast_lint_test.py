import astroid
from z3 import *
import logging

from pylint.checkers import BaseChecker
from pylint.interfaces import IAstroidChecker

def register(linter):
    linter.register_checker(AssumptionsChecker(linter))

class AssumptionsChecker(BaseChecker):
    __implements__ = IAstroidChecker

    ASSUMPTIONS_VIOLATED = 'assumptions-violated'

    name = 'assumptions-checker'
    priority = -1
    msgs = {
        'W0001': (
            'Assumptions are violated when %s() calls to %s().\nAssumtpions are: %s',
            ASSUMPTIONS_VIOLATED,
            'An assumption that you made in your code is violated'
        ),
    }
    options = (
    )

    def __init__(self, linter=None):
        super().__init__(linter)
        self.functions_assumptions = [] #list of (funcNode, assumptions_list)
        self.checked_pathes = [] #list of [func1_name, ..., funcN_name]
        self.solver = Solver()
        logging.basicConfig(level=logging.DEBUG,
                format='[%(asctime)s] %(name)s:%(levelname)s: %(message)s')
        self.logger = logging.getLogger(self.__class__.__name__)
        # self.logger.setLevel('DEBUG')
        self.logger.setLevel('INFO')

    def parse_assumption(self, assumption):
        self.logger.debug(f'asm: {assumption}')
        #TODO: add a CFL here
        asm = assumption
        is_negative = False
        if asm.startswith('no-'):
            is_negative = True
            asm = asm[len('no-'):]
        #get the symbol name
        self.logger.debug(f'symbol name: {asm}')
        symbol = Bool(asm)
        expr = symbol

        #post-parse - add the constrainst
        if is_negative:
            expr = Not(expr)

        #return the expr
        return expr

    def parse_assumptions_block(self, assumptions_block):
        '''Returns list of assumptions in z3'''
        result = []
        assumptions = [x.strip() for x in ' '.join(assumptions_block).split(',')]
        for asm in assumptions:
            expr = self.parse_assumption(asm)
            result.append(expr)
        return result

    def extract_assumptions(self, func_doc):
        assumptions = []
        assume_keyword = 'assume:'
        lines = func_doc.split('\n')
        assume_lines = []
        index = 0
        is_in_block = False
        assumptions_block = []
        pos = -1
        for line in lines:
            if line.strip().startswith(assume_keyword):
                #it starts with "assume:"
                #store the position for tracking the indentation
                pos = line.find(assume_keyword)
                if is_in_block:
                    #finish the current assumption block
                    assumptions.append(assumptions_block)
                    #create new assumption block
                    asumption_block = []
                is_in_block = True
                #add the current line to assumptions_block
                assumptions_block.append(line[pos + len(assume_keyword):].strip())
            elif is_in_block:
                if any(line[pos:].startswith(x) for x in ('  ', '\t')):
                    #add to current block
                    assumptions_block.append(line.strip())
                else:
                    #finish the current assumption block
                    assumptions.append(assumptions_block)
                    #create new assumption block
                    asumption_block = []
                    #its not an assumption block
                    is_in_block = False
        assumptions = sum([self.parse_assumptions_block(x) for x in assumptions], [])
        return assumptions

    def get_all_calls(self, node):
        calls = []
        if isinstance(node, astroid.node_classes.Call):
            #we found a call!
            calls.append(node)
        else:
            if hasattr(node, 'value'):
                calls += self.get_all_calls(node.value)
            elif hasattr(node, 'body'):
                for expr in node.body:
                    calls += self.get_all_calls(expr)
            elif hasattr(node, 'values'):
                for value in node.values():
                    calls += self.get_all_calls(value)
        return calls

    def check_assumptions(self, func, assumptions, path):
        self.logger.debug(f'{func.qname()}: {assumptions}')
        #find all calls
        calls = self.get_all_calls(func)
        for call in calls:
            #recursive add assumptions
            callee_name = call.func.name
            self.logger.debug(f'callee = {callee_name}')
            #recursive function check can be neet, but for now I won't deal with it
            if callee_name == func.name:
                continue
            matches_funcs = ((x,y) for x,y in self.functions_assumptions if x.name == callee_name)
            for callee, callee_assumptions in matches_funcs:
                #check current assumptions
                current_assumptions = assumptions + callee_assumptions
                self.solver.reset()
                for asm in current_assumptions:
                    self.solver.add(asm)
                if self.solver.check() == unsat:
                    #add message - TODO: add a path here
                    self.add_message(self.ASSUMPTIONS_VIOLATED, node=func,
                            args=('->'.join(path),callee.name,current_assumptions))
                #now - check the inner calls, but now with current_assumptions
                self.logger.debug(f'recursive: {func.qname()} called {callee.qname()}')
                self.check_assumptions(callee, current_assumptions, path=path+[callee.qname(),])

    def check_all_assumptions(self):
        self.logger.debug(f'all: {self.functions_assumptions}')
        for func,assumptions in self.functions_assumptions:
            self.check_assumptions(func, assumptions, path=[func.qname(),])

    def visit_functiondef(self, node):
        func_doc = node.doc
        assumptions = self.extract_assumptions(func_doc)
        self.functions_assumptions.append((node, assumptions))

    def leave_module(self, node):
        self.check_all_assumptions()
