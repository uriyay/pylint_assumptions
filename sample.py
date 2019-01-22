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
