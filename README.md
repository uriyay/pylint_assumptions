# pylint_assumptions

## General

**pylint_assumptions** is a pylint checker that checks a logical assumptions that you made in your code.
The checker will walk through the function declarations and will collect assumptions.
These assumptions will be checked with **z3 solver** after the **AST** walk will be done.

## Why should I use that?

You can use that instead of running a unit tests for making a behaviour constant and fix the code every time something breaks (or in addition).

As long as you write a clear expressions you can declare on a behaviour in the code. Not only in the micro-level of unit-testing and type-safty, but also in the macro-level.

Remember those **TODO** comments? like "TODO: doesn't handle a case of X".
So instead you can write an assumption that this function doesn't handle X, and when you will call this function, assuming that it does handle X, you will get a warning.

## Usage

An assumption is declared by a comment inside the function.

Let's see an example:
```python
def func1():
    '''
    assume: no-throw
    '''
    func2()

def func2():
    '''
    assume: throw
    '''
    raise Exception('hello!')
```
(from sample.py)

Here func1 assumes that there is no exception thrown, that's why it won't catch any exception.
But it calls func2 which will raise an exception.

Run pylint on this file by running:
```
./run_sample.sh
```

It will write this message:
```
W:  1, 0: Assumptions are violated when test.func1() calls to func2().
Assumtpions are: [Not(throw), throw] (assumptions-violated)
```

## Future plans
1. Adding assumptions **inside** a function
2. More soficticated logical expressions (with And, Or etc.)
