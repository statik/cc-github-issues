library(shiny)
library(httr)
library(jsonlite)
library(lubridate)
library(dplyr)
library(DT)
library(openai)
library(digest)

# Default date (2 years ago)
default_date <- format(Sys.Date() - years(2), "%Y-%m-%d")

# Azure OpenAI configuration
Sys.setenv(AZURE_OPENAI_KEY = Sys.getenv("AZURE_OPENAI_KEY"))
Sys.setenv(AZURE_OPENAI_ENDPOINT = Sys.getenv("AZURE_OPENAI_ENDPOINT"))

# Function to generate a color based on the label text
get_label_color <- function(label) {
  hash <- digest(label, algo = "md5")
  paste0("#", substr(hash, 1, 6))
}

truncate_text <- function(text, max_length = 100) {
  ifelse(nchar(text) > max_length, paste0(substr(text, 1, max_length), "..."), text)
}

ui <- fluidPage(
  tags$head(
    tags$script(HTML("
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
    ")),
    tags$style(HTML("
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
    "))
  ),
  h2("GitHub Issues Explorer"),
  tabsetPanel(
    tabPanel(
      "GitHub Issues",
      sidebarLayout(
        sidebarPanel(
          textInput("repo", "GitHub Repository", value = "rstudio/rstudio-docker-products"),
          textInput("github_token", "GitHub PAT", placeholder = "Optional"),
          dateInput("cutoff", "Cutoff Date", value = default_date),
          sliderInput("num_issues", "Number of Issues", min = 10, max = 500, value = 100, step = 10),
          actionButton("load_issues", "Load Issues"),
          textOutput("filtered_count_text"),
          downloadButton("download_json", "Download Main Table as JSON"),
          width = 3
        ),
        mainPanel(
          h3("80% of Issues"),
          DTOutput("issues_table_main"),
          h3("Remaining 20% of Issues"),
          DTOutput("issues_table_secondary")
        )
      )
    ),
    tabPanel(
      "Chat",
      sidebarLayout(
        sidebarPanel(
          radioButtons("chat_model", "Select Chat Model:", 
                       choices = c("AzureOpenAI", "Ollama"), 
                       selected = "AzureOpenAI"),
          textInput("ollama_endpoint", "Ollama Endpoint:", 
                    value = "http://localhost:11434"),
          textInput("analyze_issue", "What issue do you want to analyze?"),
          actionButton("load_issue_query", "Create Issue Query"),
          actionButton("reset_chat", "Reset chat", class = "btn-warning"),
          width = 3
        ),
        mainPanel(
          textAreaInput("system_prompt", "System Prompt", 
                        rows = 5, 
                        placeholder = "System prompt for the AI model", 
                        width = "100%", 
                        value = "You are an AI assistant helping with GitHub issues analysis. Use these related issues to decide how to label the current issue:\n```\n{issues_context}\n```"),
          uiOutput("chat")
        )
      )
    ),
    tabPanel(
      "About",
      sidebarLayout(
        sidebarPanel(
          h4("App Information"),
          p("Version: 1.0"),
          p("Last Updated: 2023-06-15"),
          width = 3
        ),
        mainPanel(
          h2("About GitHub Issues Explorer"),
          p("This app allows users to explore closed issues from specified GitHub repositories. It was created using https://gallery.shinyapps.io/shiny-claude/"),
          br(),
          h4("Features:"),
          tags$ul(
            tags$li("Fetch closed issues from any public GitHub repository"),
            tags$li("Set a cutoff date to limit the issues retrieved"),
            tags$li("Control the number of issues to fetch"),
            tags$li("View issues in an interactive table"),
            tags$li("Issues are split into two tables: 80% in the main table and 20% in the secondary table"),
            tags$li("Only issues with labels are displayed"),
            tags$li("Download main table issues as JSON for use with AzureOpenAI")
          ),
          br(),
          p("Developed using Shiny for R and the dplyr library."),
          p("For more information or to report issues, please visit our GitHub repository.")
        )
      )
    )
  )
)

server <- function(input, output, session) {
  issues_data <- reactiveVal(NULL)
  filtered_count <- reactiveVal(0)
  
  chat_messages <- reactiveVal(list(
    list(role = "system", content = "You are an AI assistant helping with GitHub issues analysis."),
    list(role = "assistant", content = "**Hello!** Would you like me to label a GitHub issue for you?")
  ))
  
  observeEvent(chat_messages(), {
    output$chat <- renderUI({
      div(
        lapply(chat_messages(), function(msg) {
          if (msg$role == "user") {
            div(class = "user-message", msg$content)
          } else if (msg$role == "assistant") {
            div(class = "assistant-message", msg$content)
          }
        }),
        textAreaInput("user_input", "Your message:"),
        actionButton("send_message", "Send")
      )
    })
  })
  
  observeEvent(input$reset_chat, {
    chat_messages(list(
      list(role = "system", content = "You are an AI assistant helping with GitHub issues analysis."),
      list(role = "assistant", content = "**Hello!** Would you like me to label a GitHub issue for you?")
    ))
  })
  
  observeEvent(input$load_issue_query, {
    issue_number <- input$analyze_issue
    if (!is.null(issues_data()) && !is.null(issue_number)) {
      df <- issues_data()
      issue <- df %>% filter(Number == as.integer(issue_number))
      if (nrow(issue) > 0) {
        title <- issue$Title[1]
        body <- issue$Body[1]
        text <- sprintf("Analyze this issue to determine which issue labels should be applied #%s: %s\n\nBody: %s", issue_number, title, body)
      } else {
        text <- sprintf("Issue #%s not found in the loaded data.", issue_number)
      }
    } else {
      text <- sprintf("No issues data loaded or invalid issue number: %s", issue_number)
    }
    updateTextAreaInput(session, "user_input", value = text)
  })
  
  observeEvent(input$load_issues, {
    repo <- input$repo
    cutoff_date <- input$cutoff
    num_issues <- input$num_issues
    
    if (repo == "") {
      showNotification("Please enter a valid repository", type = "warning")
      return()
    }
    
    repo_parts <- strsplit(repo, "/")[[1]]
    if (length(repo_parts) != 2) {
      showNotification("Invalid repository format. Use 'username/repo'", type = "error")
      return()
    }
    
    owner <- repo_parts[1]
    repo_name <- repo_parts[2]
    
    github_token <- input$github_token
    
    headers <- c("Accept" = "application/vnd.github.v3+json")
    
    if (github_token != "") {
      headers <- c(headers, Authorization = paste("token", github_token))
      showNotification("Using authenticated GitHub API requests", type = "message")
    } else {
      showNotification("GitHub token not found. Using unauthenticated requests with lower rate limits.", type = "warning")
    }
    
    withProgress(message = "Fetching issues...", value = 0, {
      url <- sprintf("https://api.github.com/repos/%s/%s/issues", owner, repo_name)
      params <- list(state = "closed", since = cutoff_date, per_page = 100)
      issues <- list()
      total_issues <- 0
      filtered_issues <- 0
      
      while (!is.null(url) && length(issues) < num_issues) {
        response <- GET(url, query = params, add_headers(.headers = headers))
        stop_for_status(response)
        new_issues <- content(response, "parsed")
        total_issues <- total_issues + length(new_issues)
        labeled_issues <- Filter(function(issue) {
          !("pull_request" %in% names(issue)) && length(issue$labels) > 0
        }, new_issues)
        filtered_issues <- filtered_issues + (length(new_issues) - length(labeled_issues))
        issues <- c(issues, labeled_issues[1:min(num_issues - length(issues), length(labeled_issues))])
        if (length(issues) >= num_issues) break
        url <- httr::headers(response)$link
        if (!is.null(url)) {
          url <- sub('.*<(.*)>; rel="next".*', "\\1", url)
        }
        params <- list()
      }
      
      setProgress(0.5, detail = "Processing data...")
      
      data <- lapply(issues, function(issue) {
        list(
          Number = issue$number,
          Title = issue$title,
          `Created At` = as.Date(issue$created_at),
          `Closed At` = as.Date(issue$closed_at),
          Labels = paste(sapply(issue$labels, function(label) label$name), collapse = ", "),
          Body = issue$body
        )
      })
      
      df <- do.call(rbind.data.frame, data)
      
      issues_data(df)
      filtered_count(filtered_issues)
      
      setProgress(1, detail = "Complete!")
    })
  })
  
  output$filtered_count_text <- renderText({
    count <- filtered_count()
    if (count > 0) {
      sprintf("Issues without labels filtered out: %d", count)
    } else {
      ""
    }
  })
  
  output$issues_table_main <- renderDT({
    if (is.null(issues_data())) return(NULL)
    df <- issues_data()
    main_count <- floor(nrow(df) * 0.8)
    df_main <- df[1:main_count, ]
    
    df_main$Number <- sprintf('<a href="https://github.com/%s/issues/%s" target="_blank">%s</a>', input$repo, df_main$Number, df_main$Number)
    df_main$Labels <- sapply(df_main$Labels, function(labels) {
      paste(sapply(strsplit(labels, ", ")[[1]], function(label) {
        sprintf('<span class="label-tag" style="background-color: %s;">%s</span>', get_label_color(label), label)
      }), collapse = " ")
    })
    df_main$Body <- sapply(df_main$Body, truncate_text)
    
    datatable(df_main, escape = FALSE, selection = "single", options = list(pageLength = 10))
  })
  
  output$issues_table_secondary <- renderDT({
    if (is.null(issues_data())) return(NULL)
    df <- issues_data()
    main_count <- floor(nrow(df) * 0.8)
    df_secondary <- df[(main_count + 1):nrow(df), ]
    
    df_secondary$Number <- sprintf('<a href="https://github.com/%s/issues/%s" target="_blank">%s</a>', input$repo, df_secondary$Number, df_secondary$Number)
    df_secondary$Labels <- sapply(df_secondary$Labels, function(labels) {
      paste(sapply(strsplit(labels, ", ")[[1]], function(label) {
        sprintf('<span class="label-tag" style="background-color: %s;">%s</span>', get_label_color(label), label)
      }), collapse = " ")
    })
    df_secondary$Body <- sapply(df_secondary$Body, truncate_text)
    
    datatable(df_secondary, escape = FALSE, selection = "single", options = list(pageLength = 10))
  })
  
  format_issues_data <- reactive({
    if (!is.null(issues_data())) {
      df <- issues_data()
      repo <- input$repo
      main_count <- floor(nrow(df) * 0.8)
      main_data <- df[1:main_count, ]
      formatted_data <- list(
        repo = repo,
        github_issues = lapply(1:nrow(main_data), function(i) {
          list(
            number = as.character(main_data$Number[i]),
            title = main_data$Title[i],
            created_at = as.character(main_data$`Created At`[i]),
            closed_at = as.character(main_data$`Closed At`[i]),
            labels = strsplit(main_data$Labels[i], ", ")[[1]],
            body = main_data$Body[i]
          )
        })
      )
      toJSON(formatted_data, pretty = TRUE, auto_unbox = TRUE)
    } else {
      "No issues data available."
    }
  })
  
  output$download_json <- downloadHandler(
    filename = function() {
      "github_issues.json"
    },
    content = function(file) {
      writeLines(format_issues_data(), file)
    }
  )
  
  observeEvent(input$selected_issue, {
    issue_number <- input$selected_issue
    if (!is.null(issue_number) && !is.null(issues_data())) {
      df <- issues_data()
      issue <- df[df$Number == as.integer(issue_number), ]
      if (nrow(issue) > 0) {
        showModal(modalDialog(
          title = sprintf("Issue #%s: %s", issue_number, issue$Title),
          p(id = "modal_body", issue$Body),
          footer = tagList(
            actionButton("copy_button", "Copy to Clipboard"),
            modalButton("Close")
          )
        ))
      }
    }
  })
  
  observeEvent(input$copy_button, {
    showNotification("Text copied to clipboard!", type = "message")
  })
  
  observeEvent(input$send_message, {
    user_message <- input$user_input
    if (user_message != "") {
      chat_messages(c(chat_messages(), list(list(role = "user", content = user_message))))
      
      issues_context <- format_issues_data()
      formatted_sys_prompt <- sprintf(input$system_prompt, issues_context = issues_context)
      
      messages <- c(list(list(role = "system", content = formatted_sys_prompt)), chat_messages())
      
      if (input$chat_model == "AzureOpenAI") {
        response <- openai::create_chat_completion(
          model = "gpt-4o",
          messages = messages,
          api_key = Sys.getenv("AZURE_OPENAI_KEY"),
          api_base = Sys.getenv("AZURE_OPENAI_ENDPOINT"),
          api_type = "azure",
          api_version = "2023-05-15"
        )
        
        assistant_message <- response$choices[[1]]$message$content
        chat_messages(c(chat_messages(), list(list(role = "assistant", content = assistant_message))))
      } else {
        # Implement Ollama chat here if needed
        showNotification("Ollama chat not implemented in this R version", type = "warning")
      }
      
      updateTextAreaInput(session, "user_input", value = "")
    }
  })
}

shinyApp(ui, server)
