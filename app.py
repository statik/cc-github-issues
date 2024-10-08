from shiny import App, ui, render, reactive

from datetime import datetime, timedelta
import polars as pl
import requests
import math
import json
import os
import hashlib

from ollama import Client as OllamaClient
from openai import AzureOpenAI
from anthropic import AnthropicBedrock

from shiny.types import ImgData
from htmltools import Tag

# Default date (2 years ago)
default_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")


# Azure OpenAI configuration
azure_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version="2023-05-15",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
)

bedrock_client = AnthropicBedrock(
    aws_profile=os.getenv("AWS_PROFILE"),
    # aws_secret_key=os.getenv("AWS_SECRET_KEY"),
    # aws_access_key=os.getenv("AWS_ACCESS_KEY"),
    # aws_region=os.getenv("AWS_REGION"),
    # aws_account_id=os.getenv("AWS_ACCOUNT_ID"),
)


# Add this function to generate a color based on the label text
def get_label_color(label):
    hash_object = hashlib.md5(label.encode())
    hex_dig = hash_object.hexdigest()
    return f"#{hex_dig[:6]}"

def truncate_text(text, max_length=100):
    return text[:max_length] + "..." if len(text) > max_length else text


app_ui = ui.page_fluid(
    ui.head_content(
        ui.tags.script(
            """
            $(document).on('click', '.clickable-row tbody tr', function() {
                let issueNumber = $(this).find('td:first').text();
                Shiny.setInputValue('selected_issue', issueNumber);
            });
            $(document).on('click', '#copy_button', function() {
                var bodyText = $('#modal_body').text();
                navigator.clipboard.writeText(bodyText).then(function() {
                    console.log('Text copied to clipboard');
                }).catch(function(err) {
                    console.error('Failed to copy text: ', err);
                });
            });
        """
        ),
        ui.tags.style(
            """
            .shiny-data-grid {
                width: 100% !important;
            }
            .issue-body {
                white-space: pre-wrap;
                word-wrap: break-word;
            }
            .label-tag {
                display: inline-block;
                padding: 2px 6px;
                margin: 2px;
                border-radius: 12px;
                font-size: 0.8em;
                font-weight: bold;
                color: white;
            }
            .clickable-row {
                cursor: pointer;
            }
        """
        ),
    ),
    ui.h2("GitHub Issues Explorer"),
    ui.navset_tab(
        ui.nav_panel(
            "GitHub Issues",
            ui.layout_sidebar(
                ui.sidebar(
                    ui.input_text(
                        "repo",
                        "GitHub Repository",
                        value="rstudio/rstudio-docker-products",
                    ),
                    ui.input_password(
                        "github_token",
                        "GitHub PAT",
                        placeholder="Optional",
                        value=os.getenv("GITHUB_TOKEN"),
                    ),
                    ui.input_date("cutoff", "Cutoff Date", value=default_date),
                    ui.input_slider(
                        "num_issues",
                        "Number of Issues",
                        min=10,
                        max=500,
                        value=100,
                        step=10,
                    ),
                    ui.input_action_button("load_issues", "Load Issues"),
                    ui.output_text("filtered_count_text"),
                    # ui.output_text("selected_issue"),
                    ui.download_button("download_json", "Download Main Table as JSON"),
                    open="open",
                ),
                ui.div(
                    ui.h3("80% of Issues"),
                    ui.output_data_frame("issues_table_main"),
                    ui.h3("Remaining 20% of Issues"),
                    ui.output_data_frame("issues_table_secondary"),
                    class_="w-100",
                ),
            ),
        ),
        ui.nav_panel(
            "Chat",
            ui.layout_sidebar(
                ui.sidebar(
                    ui.input_radio_buttons(
                        "chat_model",
                        "Select Chat Model:",
                        choices=["AzureOpenAI", "Ollama", "Claude3.5Sonnet"],
                        selected="AzureOpenAI",
                    ),
                    ui.input_text(
                        "ollama_endpoint",
                        "Ollama Endpoint:",
                        value=os.getenv(
                            "OLLAMA_ENDPOINT", default="http://localhost:11434"
                        ),
                    ),
                    ui.input_text(
                        "ollama_model",
                        "Ollama Model:",
                        value=os.getenv(
                            "OLLAMA_MODEL", default="llama3:8b"
                        ),
                    ),
                    # ui.input_selectize(
                    #     "issue",
                    #     "Select Issue:",
                    #     test_data(),
                    #     multiple=True,
                    #     options={"plugins": ["clear_button"]},
                    # ),
                    ui.input_text(
                        "analyze_issue", "What issue do you want to analyze?"
                    ),
                    ui.input_action_button("load_issue_query", "Create Issue Query"),
                    ui.input_action_button(
                        "reset_chat", "Reset chat", class_="btn-warning"
                    ),
                    open="open",
                ),
                ui.div(
                    ui.input_text_area(
                        "system_prompt",
                        "System Prompt",
                        rows=5,
                        placeholder="System prompt for the AI model",
                        width="100%",
                        autoresize=True,
                        value="""
You are an AI assistant helping with GitHub issues analysis. Use these
related issues to decide how to label the current issue:
```
{issues_context}
```""",
                    ),
                    ui.chat_ui("chat"),
                ),
            ),
        ),
        ui.nav_panel(
            "About",
            ui.layout_sidebar(
                ui.sidebar(
                    ui.h4("App Information"),
                    ui.p("Version: 1.0"),
                    ui.p("Last Updated: 2023-06-15"),
                ),
                ui.div(
                    ui.h2("About GitHub Issues Explorer"),
                    ui.p(
                        "This app allows users to explore closed issues from specified GitHub repositories. It was created using https://gallery.shinyapps.io/shiny-claude/"
                    ),
                    ui.br(),
                    ui.h4("Features:"),
                    ui.tags.ul(
                        ui.tags.li(
                            "Fetch closed issues from any public GitHub repository"
                        ),
                        ui.tags.li("Set a cutoff date to limit the issues retrieved"),
                        ui.tags.li("Control the number of issues to fetch"),
                        ui.tags.li("View issues in an interactive table"),
                        ui.tags.li(
                            "Issues are split into two tables: 80% in the main table and 20% in the secondary table"
                        ),
                        ui.tags.li("Only issues with labels are displayed"),
                        ui.tags.li(
                            "Download main table issues as JSON for use with AzureOpenAI"
                        ),
                    ),
                    ui.br(),
                    ui.p(
                        "Developed using Shiny for Python and the Polars DataFrame library."
                    ),
                    ui.p(
                        "For more information or to report issues, please visit our GitHub repository."
                    ),
                    class_="w-100",
                ),
            ),
        ),
    ),
)


def server(input, output, session):
    issues_data = reactive.Value(None)
    filtered_count = reactive.Value(0)
    test_data = reactive.Value({ "issues": { "1": "Issue 1"}})

    initial_messages = [
        {
            "role": "assistant",
            "content": "**Hello!** Would you like me to label a GitHub issue for you?",
        },
    ]

    chat = ui.Chat(id="chat", messages=initial_messages)

    @reactive.effect
    @reactive.event(chat.messages)
    def set_reset_button_state():
        if len(chat.messages()) > 2:
            ui.update_action_button("reset_chat", disabled=False)
        else:
            ui.update_action_button("reset_chat", disabled=True)

    @reactive.effect
    @reactive.event(input.reset_chat)
    async def reset():
        # print("Resetting chat")
        await chat.clear_messages()

    @reactive.effect
    @reactive.event(input.load_issue_query)
    def load():
        issue_number = input.analyze_issue()
        if issues_data() is not None and issue_number:
            df = issues_data()
            issue = df.filter(pl.col("Number") == int(issue_number))
            if issue.height > 0:
                title = issue.select("Title").item()
                body = issue.select("Body").item()
                text = f"Analyze this issue to determin which issue labels should be applied #{issue_number}: {title}\n\nBody: {body}"
            else:
                text = f"Issue #{issue_number} not found in the loaded data."
        else:
            text = f"No issues data loaded or invalid issue number: {issue_number}"

        chat.update_user_input(value=text)

    @reactive.Effect
    @reactive.event(input.load_issues)
    def load_issues():
        repo = input.repo()
        cutoff_date = input.cutoff()
        num_issues = input.num_issues()

        if not repo:
            ui.notification_show("Please enter a valid repository", type="warning")
            return

        try:
            owner, repo_name = repo.split("/")
        except ValueError:
            ui.notification_show(
                "Invalid repository format. Use 'username/repo'", type="error"
            )
            return

        # Get the GitHub token from environment variable
        github_token = input.github_token()

        headers = {"Accept": "application/vnd.github.v3+json"}

        if github_token:
            headers["Authorization"] = f"token {github_token}"
            ui.notification_show(
                "Using authenticated GitHub API requests", type="message"
            )
        else:
            ui.notification_show(
                "GitHub token not found. Using unauthenticated requests with lower rate limits.",
                type="warning",
            )

        with ui.Progress(min=0, max=100) as p:
            p.set(message="Fetching issues...", detail="This may take a moment.")

            try:
                url = f"https://api.github.com/repos/{owner}/{repo_name}/issues"
                params = {"state": "closed", "since": cutoff_date, "per_page": 100}
                issues = []
                total_issues = 0
                filtered_issues = 0

                while url and len(issues) < num_issues:
                    response = requests.get(url, params=params, headers=headers)
                    response.raise_for_status()
                    new_issues = response.json()
                    total_issues += len(new_issues)
                    labeled_issues = [
                        issue
                        for issue in new_issues
                        if "pull_request" not in issue and issue["labels"]
                    ]
                    filtered_issues += len(new_issues) - len(labeled_issues)
                    issues.extend(labeled_issues[: num_issues - len(issues)])
                    if len(issues) >= num_issues:
                        break
                    url = response.links.get("next", {}).get("url")
                    params = {}  # Clear params for subsequent requests

                p.set(50, message="Processing data...")

                data = [
                    {
                        "Number": issue["number"],
                        "Title": issue["title"],
                        "Created At": issue["created_at"],
                        "Closed At": issue["closed_at"],
                        "Labels": ", ".join(
                            [label["name"] for label in issue["labels"]]
                        ),
                        "Body": issue["body"],
                    }
                    for issue in issues
                ]

                df = pl.DataFrame(data)
                df = df.with_columns(
                    [
                        pl.col("Created At")
                        .str.strptime(pl.Date, "%Y-%m-%dT%H:%M:%SZ")
                        .dt.date()
                        .cast(pl.Utf8)
                        ,#.str.strftime("%Y-%m-%d"),
                        pl.col("Closed At")
                        .str.strptime(pl.Date, "%Y-%m-%dT%H:%M:%SZ")
                        .dt.date()
                        .cast(pl.Utf8)
                        ,#.str.strftime("%Y-%m-%d"),
                    ]
                )

                issues_data.set(df)
                filtered_count.set(filtered_issues)

                p.set(100, message="Complete!")

            except requests.RequestException as e:
                ui.notification_show(f"Error fetching issues: {str(e)}", type="error")
                return

    @output
    @render.text
    def filtered_count_text():
        count = filtered_count()
        if count > 0:
            return f"Issues without labels filtered out: {count}"
        return ""

    @output
    @render.text
    def selected_issue_text():
        return input.selected_issue()

    @output
    @render.data_frame
    def issues_table_main():
        if issues_data() is None:
            return None
        df = issues_data()
        main_count = math.floor(len(df) * 0.8)
        # Create a copy of the DataFrame to modify
        df_copy = df.head(main_count).to_pandas()

        # Convert the 'Number' column to HTML links
        repo = input.repo()
        df_copy["Number"] = df_copy["Number"].apply(
            lambda x: ui.HTML(f'<a href="https://github.com/{repo}/issues/{x}" target="_blank">{x}</a>')
        )

        # Format the 'Labels' column as colored tags
        df_copy["Labels"] = df_copy["Labels"].apply(
            lambda labels: ui.HTML(''.join([
                f'<span class="label-tag" style="background-color: {get_label_color(label)};">{label}</span>'
                for label in labels.split(", ")
            ]))
        )

        df_copy["Body"] = df_copy["Body"].apply(truncate_text)

        return render.DataTable(df_copy, selection_mode="row")

    @output
    @render.data_frame
    def issues_table_secondary():
        if issues_data() is None:
            return None
        df = issues_data()
        main_count = math.floor(len(df) * 0.8)
        df_copy = df.tail(len(df) - main_count).to_pandas()

        # Convert the 'Number' column to HTML links
        repo = input.repo()
        df_copy["Number"] = df_copy["Number"].apply(
            lambda x: ui.HTML(f'<a href="https://github.com/{repo}/issues/{x}" target="_blank">{x}</a>')
        )

        # Format the 'Labels' column as colored tags
        df_copy["Labels"] = df_copy["Labels"].apply(
            lambda labels: ui.HTML(''.join([
                f'<span class="label-tag" style="background-color: {get_label_color(label)};">{label}</span>'
                for label in labels.split(", ")
            ]))
        )

        df_copy["Body"] = df_copy["Body"].apply(truncate_text)

        return render.DataTable(df_copy, selection_mode="row", styles={ "class": "clickable-row"})

    def format_issues_data():
        if issues_data() is not None:
            df = issues_data()
            repo = input.repo()  # Get the current repository
            main_count = math.floor(len(df) * 0.8)
            main_data = df.head(main_count).to_dict(as_series=False)
            formatted_data = {
                "repo": repo,
                "github_issues": [
                    {
                        "number": str(num),
                        "title": main_data["Title"][i],
                        "created_at": str(main_data["Created At"][i]),
                        "closed_at": str(main_data["Closed At"][i]),
                        "labels": main_data["Labels"][i].split(", "),
                        "body": main_data["Body"][i],  # Include the issue body
                    }
                    for i, num in enumerate(main_data["Number"])
                ],
            }
            return json.dumps(formatted_data, indent=2)
        else:
            return "No issues data available."

    @render.download(filename="github_issues.json")
    def download_json():
        # print("Download function called")  # Debug print
        yield format_issues_data()

    @chat.on_user_submit
    async def send_message():
        issues_context = format_issues_data()
        formatted_sys_prompt = input.system_prompt().format(issues_context=issues_context)

        if input.chat_model() == "AzureOpenAI":
            messages = chat.messages(format="openai")

            # Update the system prompt
            if messages and messages[0]["role"] == "system":
                messages[0]["content"] = formatted_sys_prompt
            else:
                messages = (
                    {"role": "system", "content": formatted_sys_prompt},
                ) + messages

            # print(messages)

            response = azure_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                stream=True,
            )
            await chat.append_message_stream(response)

        elif input.chat_model() == "Ollama":
            messages = chat.messages(format="ollama")

            # Update the system prompt
            if messages and messages[0]["role"] == "system":
                messages[0]["content"] = formatted_sys_prompt
            else:
                messages = (
                    {"role": "system", "content": formatted_sys_prompt},
                ) + messages

            ollama_client = OllamaClient(host=input.ollama_endpoint())

            response = ollama_client.chat(
                model=input.ollama_model(),
                messages=messages,
                stream=True,
            )

            await chat.append_message_stream(response)

        else: # Claude 3.5 Sonnet via Bedrock
            messages = chat.messages(format="anthropic")

            # Update the system prompt
            # if messages and messages[0]["role"] == "system":
            #     messages[0]["content"] = formatted_sys_prompt
            # else:
            #     messages = (
            #         {"role": "system", "content": formatted_sys_prompt},
            #     ) + messages

            response = bedrock_client.messages.create(
                model="anthropic.claude-3-5-sonnet-20240620-v1:0",
                messages=messages,
                stream=True,
                system=formatted_sys_prompt,
                max_tokens=1000,
            )
            # Append the response stream into the chat
            await chat.append_message_stream(response)

            

    @reactive.Effect
    @reactive.event(input.selected_issue)
    def show_issue_modal():
        issue_number = input.selected_issue()
        if issue_number and issues_data() is not None:
            df = issues_data()
            issue = df.filter(pl.col("Number") == int(issue_number)).to_pandas()
            if not issue.empty:
                modal_content = ui.modal(
                    ui.h3(f"Issue #{issue_number}: {issue['Title'].iloc[0]}"),
                    ui.p(issue["Body"].iloc[0], id="modal_body"),
                    ui.input_action_button("copy_button", "Copy to Clipboard"),
                    title="Issue Details",
                    easy_close=True,
                    footer=None,
                )
                ui.modal_show(modal_content)

    @reactive.Effect
    @reactive.event(input.copy_button)
    def copy_to_clipboard():
        ui.notification_show("Text copied to clipboard!", type="message")


app = App(app_ui, server)
