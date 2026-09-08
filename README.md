# Argo

> **Explore information. Verify evidence. Understand data.**

**Argo** is an AI-powered data exploration and research system designed to help users discover, collect, validate, and analyze real-world information.

The project takes inspiration from the **Argonauts** of Greek mythology—explorers who embarked on a journey aboard the ship **Argo** to discover the unknown.

The first implementation focuses on **Vietnamese bank interest rates**, allowing users to explore, compare, and analyze interest-rate data through a structured data pipeline.

## Features

* Explore and collect real-world data
* Compare Vietnamese bank interest rates
* Analyze data across banks and deposit terms
* Track historical observations through snapshots
* Validate and cross-check collected data
* Generate insights from validated data
* Preserve data provenance and evidence

## Overview

```text
User Query
    ↓
Explore
    ↓
Collect Data
    ↓
Validate & Verify
    ↓
Store Evidence
    ↓
Analyze
    ↓
Visualize
    ↓
Generate Insights
```

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/BaoVo1126/argo.git
cd argo
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

**Windows**

```bash
.venv\Scripts\activate
```

**macOS / Linux**

```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file based on the provided example:

```bash
cp .env.example .env
```

Then configure the required environment variables.

### 5. Run the application

```bash
python main.py
```

> The exact run command may vary depending on the application entry point.

---



If you find this project interesting, feel free to give it a star.
