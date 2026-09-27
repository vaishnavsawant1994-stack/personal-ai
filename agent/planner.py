class Planner:
    def __init__(self,models,tools): self.models=models; self.tools=tools
    def plan(self,goal,context=""):
        prompt=f"""
Goal: {goal}

Available tools:
{self.tools.schema_text()}

Context:
{context or "(none)"}

Return valid JSON only:
{{"goal":"...","steps":[{{"tool":"name","description":"...","parameters":{{}}}}]}}

Use minimum necessary steps. Do not invent tools.
If no tool is required, return an empty steps list.
"""
        return self.models.json(prompt,system="You are a conservative task planner. Return JSON only.")
