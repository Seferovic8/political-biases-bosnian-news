# Model artefacts

Drop the trained models here (or point the env vars in `config/settings.py`
at another location). The layout mirrors the evaluation / inference notebooks:

```
models/
├── models2/               # LogReg binary  -> <topic>__logreg_binary.joblib
├── models_stance/         # LogReg stance  -> <topic>__logreg_stance.joblib
├── bertic_models/         # BERTić binary  -> HF model dir per topic
└── bertic_stance_models/  # BERTić stance  -> HF model dir per topic
```

Topics: `euroatlantske_integracije`, `negiranje_genocida`,
`gradjanska_vs_konstitutivni`, `izborna_reforma`.

When these files are present the app automatically switches from **demo mode**
to **live models**. Until then it runs a transparent keyword heuristic so the
interface is fully usable.
