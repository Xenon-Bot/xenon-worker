from dataclasses import dataclass


@dataclass()
class Format:
    color: int = 0x36393E
    title: str = None
    icon: str = None


class Formatter:
    DEFAULT = Format()
    INFO = Format(title="Info", color=0x3db1ff)
    SUCCESS = Format(title="Success", color=0x3dff91)
    WARNING = Format(title="Warning", color=0xffd23d)
    ERROR = Format(title="Error", color=0xff5a3d)
    WORKING = Format(title="Please Wait ...")
    WAITING = Format(title="Waiting for Input ...")

    def format(self, content="", *, embed=None, f: Format = DEFAULT, **kwargs):
        formatted = {
            "color": f.color,
            "description": content,
            "author": {
                "name": f.title,
                "icon_url": f.icon
            }
        }

        if embed is not None:
            formatted.update(embed)

        return dict(
            embed=formatted,
            **kwargs
        )
