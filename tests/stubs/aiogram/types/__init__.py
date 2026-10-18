class _Obj:
    def __init__(self, **k): self.__dict__.update(k)
class Message(_Obj): pass
class CallbackQuery(_Obj): pass
class ChatMemberUpdated(_Obj): pass
class InlineKeyboardButton(_Obj): pass
class InlineKeyboardMarkup(_Obj): pass
class BufferedInputFile(_Obj):
    def __init__(self, data, filename=None): self.data, self.filename = data, filename
class ReplyParameters(_Obj): pass
class BotCommand(_Obj): pass
class BotCommandScopeAllGroupChats(_Obj): pass
class BotCommandScopeAllPrivateChats(_Obj): pass
class ErrorEvent(_Obj): pass
