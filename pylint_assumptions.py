import astroid
from z3 import *
import logging

from pylint.checkers import BaseChecker
from pylint.interfaces import IRawChecker

ASSUME_KEYWORD = 'assume:'

def register(linter):
    linter.register_checker(AssumptionsChecker(linter))

class AssumptionsChecker(BaseChecker):
    __implements__ = IRawChecker

    ASSUMPTIONS_VIOLATED = 'assumptions-violated'

    name = 'assumptions-checker'
    priority = -1
    msgs = {
        'W0001': (
            '\n'.join(['Assumptions are violated when %s() calls to %s().',
                '\tCaller assumtpions are: %s', '\tWhile callee assumptions are: %s',
                '\tThe bad assumption is: %s']),
            ASSUMPTIONS_VIOLATED,
            'An assumption that you made in your code is violated'
        ),
    }
    options = (
    )

    def __init__(self, linter=None):
        super().__init__(linter)
        self.module_text = None
        self.module_lines = None
        self.module_node = None
        self.functions_assumptions = [] #list of (funcNode, assumptions_list)
        self.checked_pathes = [] #list of [func1_name, ..., funcN_name]
        self.solver = Solver()
        logging.basicConfig(level=logging.DEBUG,
                format='[%(asctime)s] %(name)s:%(levelname)s: %(message)s')
        self.logger = logging.getLogger(self.__class__.__name__)
        # self.logger.setLevel('DEBUG')
        self.logger.setLevel('INFO')

    def parse_assumption(self, assumption, node):
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

    def parse_assumptions_block(self, assumptions_block, node):
        '''Returns list of assumptions in z3'''
        result = []
        assumptions = [x.strip() for x in ' '.join(assumptions_block).split(',')]
        for asm in assumptions:
            expr = self.parse_assumption(asm, node)
            result.append(expr)
        return result

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

    def check_assumptions(self, func, assumptions, comments_assumptions, path):
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
            matches_funcs = ((x,y,z) for x,y,z in self.functions_assumptions if x.name == callee_name)
            for callee, callee_assumptions, callee_comments_assumptions in matches_funcs:
                #check current assumptions
                self.solver.reset()
                for asm in assumptions:
                    self.solver.add(asm)
                    #TODO: self.solver.check() here
                for line,comment_asm in comments_assumptions:
                    #if its before the call
                    if line < call.fromlineno:
                        #TODO: what is the path that leads to the call is never going here?
                        self.solver.add(comment_asm)

                #add callee_assumptions
                should_skip_recursive = False
                for asm in callee_assumptions:
                    self.solver.add(asm)
                    if self.solver.check() == unsat:
                        self.add_message(self.ASSUMPTIONS_VIOLATED, line=func.fromlineno,
                            args=('->'.join(path),callee.name,assumptions,callee_assumptions,asm))
                        #do not continue - we might not know if there is another assumption violation
                        #or if its the current assumption
                        should_skip_recursive = True
                        break
                if not should_skip_recursive:
                    #now - check the inner calls, but now with current_assumptions
                    self.logger.debug(f'recursive: {func.qname()} called {callee.qname()}')
                    current_assumptions = assumptions + callee_assumptions
                    self.check_assumptions(callee, current_assumptions, path=path+[callee.qname(),])

    def check_all_assumptions(self):
        for func, assumptions, comments_assumptions in self.functions_assumptions:
            self.check_assumptions(func, assumptions, comments_assumptions, path=[func.qname(),])

    def extract_assumptions_from_funcdef(self, node):
        assumptions = []
        #TODO: add support in comments assumptions inside the function
        func_doc = node.doc
        lines = func_doc.split('\n')
        assume_lines = []
        index = 0
        is_in_block = False
        assumptions_block = []
        pos = -1
        for line in lines:
            if line.strip().startswith(ASSUME_KEYWORD):
                #it starts with "assume:"
                #store the position for tracking the indentation
                pos = line.find(ASSUME_KEYWORD)
                if is_in_block:
                    #finish the current assumption block
                    assumptions.append(assumptions_block)
                    #create new assumption block
                    asumption_block = []
                is_in_block = True
                #add the current line to assumptions_block
                assumptions_block.append(line[pos + len(ASSUME_KEYWORD):].strip())
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
        assumptions = sum([self.parse_assumptions_block(x, node) for x in assumptions], [])
        return assumptions

    def extract_assumptions_from_comment(self, comment, node):
        assumptions = None
        comment = comment.strip()
        if comment.startswith(ASSUME_KEYWORD):
            pos = comment.find(ASSUME_KEYWORD)
            assumptions_block = comment[pos + len(ASSUME_KEYWORD):]
            assumptions = self.parse_assumptions_block(assumptions_block, node)
        return assumptions

    def process_comments(self, node, start, end):
        comments_assumptions = {}
        for index, line in enumerate(self.module_lines[start:end]):
            if line.lstrip().startswith('#'):
                assumptions = self.extract_assumptions_from_comment(line, node)
                if assumptions is not None:
                    comments_assumptions[index] = assumptions
        return comments_assumptions

    def process_module(self, node):
        self.module_text = node.stream().read().decode()
        self.module_lines = self.module_text.split('\n')
        self.module_node = astroid.parse(self.module_text)

        for funcdef in self.module_node.nodes_of_class(astroid.FunctionDef):
            assumptions = self.extract_assumptions_from_funcdef(funcdef)
            comments_assumptions = self.process_comments(funcdef, funcdef.fromlineno, funcdef.tolineno)
            self.functions_assumptions.append((funcdef, assumptions, comments_assumptions))
        self.check_all_assumptions()
            
    # def visit_functiondef(self, node):
    #     import ipdb; ipdb.set_trace()
    #     assumptions = self.extract_assumptions_from_funcdef(node)
    #     self.functions_assumptions.append((node, assumptions))

    # def leave_module(self, node):
    #     self.check_all_assumptions()
