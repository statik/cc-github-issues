from shiny import App, ui, render, reactive
from shinyswatch import theme
from datetime import datetime, timedelta
from github import Github
import polars as pl

# Initialize the GitHub client
g = Github()

# Default date (2 years ago)
default_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")

app_ui = ui.page_fluid(
    theme.superhero(),
    ui.layout_sidebar(
        ui.panel_sidebar(
            ui.input_text("repo", "GitHub Repository", placeholder="user/repo"),
            ui.input_date("cutoff", "Cutoff Date", value=default_date),
            ui.input_action_button("load_issues", "Load Issues"),
        ),
        ui.panel_main(
            ui.h2("Closed Issues with Labels"),
            ui.output_table("issues_table"),
        ),
    ),
)

def server(input, output, session):
    @reactive.Effect
    @reactive.event(input.load_issues)
    def load_issues():
        repo_name = input.repo()
        cutoff_date = input.cutoff()
        
        if not repo_name:
            ui.notification_show("Please enter a repository name", type="error")
            return
        
        try:
            repo = g.get_repo(repo_name)
            issues = repo.get_issues(state='closed', since=cutoff_date)
            
            data = []
            for issue in issues:
                labels = [label.name for label in issue.labels]
                if labels:  # Only include issues with labels
                    data.append({
                        'Number': issue.number,
                        'Title': issue.title,
                        'Created At': issue.created_at,
                        'Closed At': issue.closed_at,
                        'Labels': ', '.join(labels)
                    })
            
            issues_df = pl.DataFrame(data)
            
            @output
            @render.table
            def issues_table():
                return issues_df.to_pandas()  # Convert to pandas for Shiny table output
            
            ui.notification_show(f"Loaded {len(data)} issues with labels", type="message")
        
        except Exception as e:
            ui.notification_show(f"Error: {str(e)}", type="error")

app = App(app_ui, server)