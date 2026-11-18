"""Optional opt-in AI review adapter. Offline operation is the default."""
from __future__ import annotations
import json, os, urllib.request
from dataclasses import dataclass

@dataclass
class AIConfig:
    endpoint: str
    model: str
    api_key_env: str = "BIOLOGIE_AI_API_KEY"
    timeout_seconds: int = 45

class AIUnavailable(RuntimeError): pass

class OpenAICompatibleClient:
    """Compatible chat-completions endpoint; called only after explicit user action."""
    def __init__(self, config: AIConfig):
        self.config=config

    def review_text(self, instruction: str, selected_text: str, consent: bool=False) -> dict:
        if not consent:
            raise AIUnavailable("Externe AI is niet aangeroepen: expliciete toestemming ontbreekt.")
        key=os.environ.get(self.config.api_key_env)
        if not key:
            raise AIUnavailable(f"API-sleutel ontbreekt in omgevingsvariabele {self.config.api_key_env}.")
        if not self.config.endpoint.startswith("https://"):
            raise AIUnavailable("Gebruik uitsluitend een HTTPS-endpoint.")
        payload={"model":self.config.model,"messages":[
            {"role":"system","content":"Je bent een controle-assistent voor biologie-examens. Verzin geen broninhoud. Benoem onzekerheid. Geef voorstellen, geen goedkeuring."},
            {"role":"user","content":instruction+"\n\nGeselecteerde tekst:\n"+selected_text}
        ],"temperature":0}
        request=urllib.request.Request(self.config.endpoint,data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
        try:
            with urllib.request.urlopen(request,timeout=self.config.timeout_seconds) as response:
                data=json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise AIUnavailable(f"AI-verzoek is mislukt: {exc}") from exc
        choices=data.get("choices") or []
        if not choices:
            raise AIUnavailable("De AI-dienst gaf geen bruikbaar antwoord.")
        return {"proposal":choices[0].get("message",{}).get("content",""),
                "provider_model":data.get("model",self.config.model),
                "human_approval_required":True,
                "sent_text_characters":len(selected_text)}
