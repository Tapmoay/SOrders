from sqlalchemy.exc import OperationalError, ProgrammingError
print("OperationalError bases:", [c.__name__ for c in OperationalError.__mro__[:4]])
print("ProgrammingError bases:", [c.__name__ for c in ProgrammingError.__mro__[:4]])
print("ProgrammingError subclass of OperationalError:", issubclass(ProgrammingError, OperationalError))