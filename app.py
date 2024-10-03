from shiny import App, ui, render, reactive
from datetime import datetime, timedelta
import polars as pl
import requests
import math
import json
import os

from openai import AzureOpenAI
from shiny.types import ImgData
from htmltools import Tag

# Default date (2 years ago)
default_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")

# Azure OpenAI configuration
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version="2023-05-15",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
)

app_ui = ui.page_fluid(
    ui.head_content(
        ui.tags.style(
            """
            .dataTable {
                width: 100% !important;
            }
            .dataTables_scrollBody {
                width: 100% !important;
            }
            .dataTables_wrapper {
                width: 100% !important;
            }
            .issue-body {
                white-space: pre-wrap;
                word-wrap: break-word;
            }
        """
        )
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
                    ui.download_button("download_json", "Download Main Table as JSON"),
                    open="open",
                ),
                ui.div(
                    ui.h3("80% of Issues"),
                    ui.output_data_frame("issues_table_main"),
                    ui.h3("Remaining 20% of Issues"),
                    ui.output_data_frame("issues_table_secondary"),
                    ui.modal(
                        "issue_body_modal",
                        ui.output_ui("issue_body_content"),
                        title="Issue Body",
                        easy_close=True,
                        footer=None,
                    ),
                    class_="w-100",
                ),
            ),
        ),
        ui.nav_panel(
            "Chat",
            ui.layout_sidebar(
                ui.sidebar(
                    ui.input_text("user_input", "Enter your message:"),
                    ui.input_action_button("send", "Send"),
                ),
                ui.div(
                    ui.output_ui("chat_history"),
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
                            "Download main table issues as JSON for use with OpenAI"
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
    chat_messages = reactive.Value([])

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
        github_token = os.environ.get("GITHUB_TOKEN")

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
                    response = requests.get(url, params=params)
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
                        .dt.date(),
                        pl.col("Closed At")
                        .str.strptime(pl.Date, "%Y-%m-%dT%H:%M:%SZ")
                        .dt.date(),
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
            lambda x: f'<a href="https://github.com/{repo}/issues/{x}" target="_blank">{x}</a>'
        )

        return render.DataTable(df_copy.drop(columns=["Body"]))

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
            lambda x: f'<a href="https://github.com/{repo}/issues/{x}" target="_blank">{x}</a>'
        )
        return render.DataTable(df_copy.drop(columns=["Body"]))

    @output
    @render.ui
    def issue_body_content():
        issue_number = input.show_issue_body()
        if issue_number and issues_data() is not None:
            df = issues_data()
            issue = df.filter(pl.col("Number") == int(issue_number)).to_pandas()
            if not issue.empty:
                return ui.div(
                    ui.h3(f"Issue #{issue_number}: {issue['Title'].iloc[0]}"),
                    ui.p(ui.HTML(issue["Body"].iloc[0]), class_="issue-body"),
                )
        return ui.p("No issue body available.")

    @reactive.Effect
    @reactive.event(input.show_issue_body)
    def show_issue_body():
        ui.modal_show("issue_body_modal")

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

    @reactive.Effect
    @reactive.event(input.send)
    def send_message():
        user_message = input.user_input()
        if user_message:
            # Add user message to chat history
            chat_messages.set(chat_messages() + [("user", user_message)])

            # Get the context from the first 80% of issues
            # Get the formatted issues data
            issues_context = format_issues_data()

            # Prepare the messages for the API call
            messages = [
                {
                    "role": "system",
                    "content": f"You are an AI assistant helping with GitHub issues analysis. Here's the context of the issues:\n\n{issues_context}",
                },
                {"role": "user", "content": user_message},
            ]

            # Call Azure OpenAI API
            response = client.chat.completions.create(
                model="gpt-4o",  # Replace with your actual deployed model name
                messages=messages,
            )

            # Extract the assistant's reply
            assistant_reply = response.choices[0].message.content

            # Add assistant's reply to chat history
            chat_messages.set(chat_messages() + [("assistant", assistant_reply)])

    @output
    @render.ui
    def chat_history():
        return ui.div(
            [
                ui.p(f"{'You' if role == 'user' else 'Assistant'}: {message}")
                for role, message in chat_messages()
            ]
        )


app = App(app_ui, server)
