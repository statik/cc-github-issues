# GitHub Issues Explorer

[![deploy to connect-blue](https://cdn.connect.posit.cloud/assets/deploy-to-connect-blue.svg)](https://connect.posit.cloud/publish?contentType=shiny&sourceRepositoryURL=https%3A%2F%2Fgithub.com%2Fstatik%2Fcc-github-issues&sourceRef=main&sourceRefType=branch&primaryFile=app.py&pythonVersion=3.11)

## Overview

GitHub Issues Explorer is a Shiny for Python application that allows users to fetch and explore closed issues from any public GitHub repository. It provides an interactive interface to view and analyze GitHub issues, making it easier to understand the history and patterns of issue resolution in a project.

## Features

- Fetch closed issues from any public GitHub repository
- Set a cutoff date to limit the issues retrieved
- Control the number of issues to fetch
- View issues in interactive tables
- Display issues split into two tables: 80% in the main table and 20% in the secondary table
- Show only issues with labels
- Download main table issues as JSON for use with OpenAI (excluding creation and closing dates)

## Installation

To run this application locally, follow these steps:

1. Clone this repository:

```bash
git clone https://github.com/yourusername/github-issues-explorer.git cd github-issues-explorer
```

2. Install the required dependencies:

```bash
pip install -r requirements.txt
```

3. Run the application:

```bash
python -m shiny run --port 62887 --reload --autoreload-port 62888 app.py
```
