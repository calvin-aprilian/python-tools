# Automated API Vulnerability Scanner

Custom Python & Node.js tool integrating multi-threading and asynchronous processes to **automate detection of common API misconfigurations and endpoint exposure**.

> Part of a security research workflow — used to streamline reconnaissance phases during security assessments, significantly reducing manual testing time.

## 🔧 Features

- Multi-threaded & async endpoint discovery
- API misconfiguration detection (auth bypass, excessive data exposure, CORS, rate-limit issues)
- Recon automation for security assessments
- Lightweight, scriptable, terminal-first

## 🚀 Usage

```bash
python3 scanner.py --target https://api.example.com --threads 10
```

*Note: For authorized security assessments only. Use responsibly with proper scope.*

## 🛠️ Stack

Python, Node.js, asyncio / threading, HTTP tooling

## 📄 License

MIT

---

*Security research tooling — see [my profile](https://github.com/calvin-aprilian) for more.*
