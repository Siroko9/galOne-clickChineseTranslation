class GalError(Exception):
    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code = code


class IllegalTransition(GalError):
    def __init__(self, state, event):
        super().__init__("ILLEGAL_TRANSITION", "%s + %s" % (state, event))
        self.state = state
        self.event = event


class GlossaryError(GalError):
    def __init__(self, message):
        super().__init__("GLOSSARY", message)


class ApplyFailed(GalError):
    def __init__(self, restored):
        code = "VERIFY_FAILED" if restored else "RESTORE_FAILED"
        super().__init__(code, code)
        self.restored = restored
