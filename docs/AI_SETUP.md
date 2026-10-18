# Setting up the AI assistant

The AI assistant is **optional** and **off** until you turn it on. Locuvi works fully without
it, and reads most simple booking emails by itself.

With it on, the assistant can:

- 📨 read messy booking emails, scanned letters and photos, and suggest the sessions to add
- ✨ answer questions in **Ask Locuvi**, such as *"Which practices still owe me money?"*
- 📝 prepare invoice drafts and email drafts for you to check
- 📬 write a short summary at the top of your Monday email (if you choose; the weekly email
  is set up in **Settings › Email invoices**)

It can **never** issue an invoice, send an email, record a payment or submit a pension form.
Every suggestion waits for you to approve it, and Locuvi checks every figure itself.
Calculations never use AI.

## Choose an AI company

You use your **own account** with an AI company and pay them directly for what you use. Light
use usually costs very little, and most companies let you set a monthly spending limit. Pick
whichever you prefer:

| Company | Models | Official reference | Get a key | Good to know |
| --- | --- | --- | --- | --- |
| **OpenAI** 🇺🇸 | GPT | [Models](https://platform.openai.com/docs/models) · [Pricing](https://openai.com/api/pricing/) | [platform.openai.com](https://platform.openai.com/api-keys) | Reads emails and photos |
| **Anthropic** 🇺🇸 | Claude | [Models](https://docs.claude.com/en/docs/about-claude/models/overview) · [Pricing](https://claude.com/pricing#api) | [console.anthropic.com](https://console.anthropic.com/settings/keys) | Locuvi's default. Reads emails, PDFs (including scans) and photos |
| **Google** 🇺🇸 | Gemini | [Models](https://ai.google.dev/gemini-api/docs/models) · [Pricing](https://ai.google.dev/gemini-api/docs/pricing) | [aistudio.google.com](https://aistudio.google.com/apikey) | Use a key with billing on: on the free tier Google may use what you send to improve its products |
| **xAI** 🇺🇸 | Grok | [Models](https://docs.x.ai/docs/models) · [Pricing](https://x.ai/api) | [console.x.ai](https://console.x.ai) | Reads emails and photos |
| **Mistral** 🇫🇷 | Mistral, Codestral | [Models](https://docs.mistral.ai/getting-started/models/) · [Pricing](https://mistral.ai/pricing#api-pricing) | [console.mistral.ai](https://console.mistral.ai/api-keys) | European company |
| **Cohere** 🇨🇦 | Command | [Models](https://docs.cohere.com/docs/models) · [Pricing](https://cohere.com/pricing) | [dashboard.cohere.com](https://dashboard.cohere.com/api-keys) | Reads booking text (not photos) |
| **DeepSeek** 🇨🇳 | DeepSeek | [Models & pricing](https://api-docs.deepseek.com/quick_start/pricing) | [platform.deepseek.com](https://platform.deepseek.com/api_keys) | Low cost. Reads photos only with a vision model such as `deepseek-v4-flash-vision-exp` |
| **Alibaba** 🇨🇳 | Qwen | [Models](https://www.alibabacloud.com/help/en/model-studio/models) | [Model Studio](https://modelstudio.console.alibabacloud.com/) | Uses the international (Singapore) endpoint; your key must be from the same region. Photos with a `-vl` model |
| **Moonshot AI** 🇨🇳 | Kimi | [API docs](https://platform.moonshot.ai/docs) · [Pricing](https://platform.moonshot.ai/docs/pricing/chat) | [platform.moonshot.ai](https://platform.moonshot.ai/console/api-keys) | Reads booking text (not photos) |
| **Z.ai** 🇨🇳 | GLM | [Models & API](https://docs.z.ai/guides/overview/pricing) | [z.ai](https://z.ai/manage-apikey/apikey-list) | General API key (not a GLM Coding Plan key). Photos with a vision model such as `glm-4.5v` |
| **MiniMax** 🇨🇳 | MiniMax | [Models & API](https://platform.minimax.io/docs) | [platform.minimax.io](https://platform.minimax.io/user-center/basic-information/interface-key) | Reads booking text (not photos) |
| **OpenRouter** | Many companies | [Models & prices](https://openrouter.ai/models) | [openrouter.ai](https://openrouter.ai/keys) | One key for models from many companies |
| **Your own server** 🖥 | Any | See below | Usually none | A model you run yourself, or your organisation's own AI server. [How](#use-your-own-server) |

The flag shows where each company is based. With companies based in China, your data is
usually processed there; check each company's data terms (see
[What is sent](#what-is-sent-to-the-ai-company)).

Prices change often and are set by each company, per million "tokens" (roughly ¾ of a word).
Reading one booking email uses a few thousand tokens, so it usually costs well under a penny
with the cheaper models.

**Scanned PDFs** (pictures of pages, with no text you can select) can only be read by
Anthropic (Claude). With the other companies, Locuvi reads a PDF's text, and photos go to companies
and models that can see images.

> [!NOTE]
> A ChatGPT Plus, Claude Pro or Gemini app subscription is **not** the same as an API key. API
> keys come from the developer pages linked above, and usually need a payment card or credit
> added first.

## Turn it on

<img src="images/settings-assistant.png" alt="Settings › Assistant: switch, AI company, your API key, model, and Check key">

1. Create a key on your chosen company's website (links above). Copy it. It's a long code,
   often starting with `sk-`.
2. In Locuvi, open **Settings › Assistant** and switch on **Use AI to help with bookings**.
3. Choose your **AI company**.
4. Paste the key into **Your API key** and tap **Save**.
5. Tap **Check key**. Locuvi asks the company which models your key can use. This is free.
   Companies that don't publish a model list (Cohere, Z.ai, MiniMax) get one
   one-word test request instead, which costs a tiny fraction of a penny.
   You should see *"Your key works"*.

**Model** is filled in for you. Leave it as it is unless you know you want another one; after
**Check key**, the box suggests the models your key can use.

> [!TIP]
> Changing to a different AI company forgets the saved key, so one company's key is never sent
> to another. Paste the new company's key and tap **Save**.

## Use your own server

Already run an AI model yourself, or does your organisation have its own AI server? Locuvi
can use any server with an **OpenAI-compatible API**, which most do: [Ollama](https://ollama.com),
[LM Studio](https://lmstudio.ai), [vLLM](https://docs.vllm.ai), [llama.cpp](https://github.com/ggml-org/llama.cpp),
[LocalAI](https://localai.io) and many company AI gateways.

The big advantage: **booking text never leaves your network.**

1. In **Settings › Assistant**, choose **Your own server (Ollama, LM Studio…)**.
2. **Server address**: the address of its OpenAI-compatible API, usually ending in `/v1`:

   | Where your model runs | Server address |
   | --- | --- |
   | Ollama on the **same computer** as Locuvi | `http://host.docker.internal:11434/v1` |
   | LM Studio on the same computer | `http://host.docker.internal:1234/v1` |
   | Another computer on your home network | `http://192.168.1.50:11434/v1` (that computer's address) |
   | A server elsewhere, over Tailscale | `http://<its Tailscale name or address>:11434/v1` |
   | Your organisation's AI server | the address your IT team gives you |

3. **Your API key**: leave empty unless your server asks for one.
4. **Model**: the model's name on your server, for example `llama3.1` or `qwen3`. Tap
   **Save**, then **Check key** to see the models your server offers.

> [!TIP]
> **Which model?** Booking emails are short, so a mid-sized model (around 8 billion
> parameters or more) usually reads them well. For **Ask Locuvi**, choose a model that
> supports "tools" (function calling). Smaller models make more mistakes, but Locuvi always
> shows you the suggestions to check, and checks the figures itself.

<details>
<summary><b>For the person running the server</b>: making Ollama reachable</summary>

- `host.docker.internal` reaches the computer Locuvi runs on. Locuvi's
  `docker-compose.yml` already sets this up.
- Ollama only listens to its own computer by default. For Locuvi in Docker (or another
  computer) to reach it, start Ollama with `OLLAMA_HOST=0.0.0.0`
  ([Ollama FAQ](https://github.com/ollama/ollama/blob/main/docs/faq.md)), and keep its port
  (11434) closed to the internet.
- In LM Studio, turn on **Serve on Local Network** in the Developer tab.
- For safety, Locuvi refuses cloud-metadata and link-local addresses here.

</details>

## What is sent to the AI company

- **For booking suggestions**: the booking text, your practice names and today's date.
  Before sending, Locuvi removes lines about patients, and email addresses, phone numbers,
  postcodes, and NHS and bank account numbers. It can't guarantee every detail is removed, so
  **never upload patient information**.
- **Photos and scans** can't be cleaned up first, so Locuvi asks you before sending each one.
- **Ask Locuvi** can look up your invoices, payments and diary to answer your question.
  Your bank details and passwords are never sent.
- Your key is stored **encrypted** on your server and is never shown again.

Each suggestion records which AI model made it.

## Turning it off

Switch off **Use AI to help with bookings**. To remove the key completely, tap
**Delete saved AI key**. You can also delete the key on the AI company's website at any time.

---

<details>
<summary><b>For the person running the server</b></summary>

- The key can also come from a file instead of the screen: mount it as a Docker secret and set
  `ANTHROPIC_API_KEY_FILE`. This is used only when the company is Anthropic.
- `LOCUVI_AI_MODEL` changes the default Anthropic model.
- The server needs outgoing HTTPS access to the chosen company's API.
- Tests and the e2e checks never call a real AI service (`e2e/fake_anthropic.py`, fake HTTP
  transports in `backend/tests/test_ai_providers.py`).

</details>
