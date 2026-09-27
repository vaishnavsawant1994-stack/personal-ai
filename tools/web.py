import webbrowser, urllib.parse
from tools.registry import Tool, Risk

def register(reg):
    reg.register(Tool("open_url","Open URL; params: url",
                      lambda p:(webbrowser.open(str(p["url"])) or True),Risk.EXTERNAL_SIDE_EFFECT))
    def search(p):
        q=urllib.parse.quote_plus(str(p["query"]))
        url=f"https://www.google.com/search?q={q}"
        webbrowser.open(url)
        return {"ok":True,"url":url}
    reg.register(Tool("web_search_browser","Open web search in browser; params: query",search,Risk.EXTERNAL_SIDE_EFFECT))
