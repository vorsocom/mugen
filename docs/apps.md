# Building muGen Applications

muGen is a lightweight microframework designed for developers who need flexibility and customization. It provides foundational components for building applications but does not include built-in solutions for complex, real-world use cases. To address these, developers can extend muGen by adding custom code and functionality. This guide will walk you through setting up a project directory and integrating muGen to start building your application.

## Prerequisites

Before starting, ensure the following:

1. You have a GitHub (or similar) repository set up for source control.

2. You are familiar with basic command-line usage and have Git installed on your system.

## Creating a New Application Repository

To simplify integration and keep your project up-to-date with muGen releases, create a Git repository (downstream) that tracks the muGen core (upstream). The key principle is: **NEVER modify the muGen core**. This ensures you can easily update your project with changes from the upstream repository without encountering conflicts.

### Step 1: Set Up Your Project Repository

First, create a new directory for your application and initialize it as a Git repository. This sets up your project folder and prepares it for tracking changes.

```shell
~$ mkdir genapp
~$ cd genapp
~$ git init
```

Next, create a file for tracking application-specific metadata. This file will help you document important details about your project. For this guide, we'll use a Python file named `downstream.py`:

```shell
~$ touch downstream.py
```

### Step 2: Add Project Metadata

Open `downstream.py` in a text editor and add the following basic project metadata. This information helps keep track of your application's details and can be used within your code:

```python
"""Custom metadata for the downstream application."""

__app__ = "My Awesome GenAI App"
__author__ = "Your Name"
__copyright__ = "Project copyright notice"
__email__ = "Project contact email"
__version__ = "0.0.0"
```

### Step 3: Commit Your Changes

Use the metadata file for your initial commit to the repository. Committing is the process of saving changes in Git. The project repository will be associated with a remote named `origin`:

```shell
~$ git add downstream.py
~$ git commit -m "Initial commit"
~$ git branch -M main
~$ git remote add origin [project-repo-url]
~$ git push -u origin main
~$ git checkout -b develop
~$ git push -u origin develop
```

- `git add downstream.py` stages the file for committing.
- `git commit -m "Initial commit"` saves the changes with a message.
- `git branch -M main` renames the default branch to "main."
- `git remote add origin [project-repo-url]` connects your local repository to the remote repository on GitHub.
- `git push -u origin main` uploads your main branch to GitHub.
- `git checkout -b develop` creates and switches to a new branch called "develop."
- `git push -u origin develop` pushes the new branch to the remote repository.

## Integrating muGen

### Step 4: Merge Upstream/main onto Develop

Now you’ll integrate muGen into your project. This involves setting up the upstream repository (muGen's official repository) and merging its main branch into your "develop" branch.

```shell
# Ensure you are on the development branch.
~$ git checkout develop

# Add the upstream repository.
~$ git remote add upstream git@github.com:vorsocom/mugen.git

# Prevent accidental pushes to the upstream repository.
~$ git remote set-url --push upstream PUSH_DISABLED

# Fetch the latest changes from the upstream repository.
~$ git fetch upstream main:upstream/main --no-tags

# Merge the upstream main branch into your develop branch.
~$ git merge upstream/main

# Push the updated develop branch to your GitHub repository.
~$ git push origin develop
```

### Step 5: Create the muGen Configuration File

muGen requires a configuration file named `mugen.toml` for its settings. Create it by copying a sample file provided in the muGen repository:

```shell
~$ cp conf/mugen.toml.sample mugen.toml
```

The default configurations can be used initially. However, you must configure access credentials for your chosen completion API provider (e.g., AWS Bedrock, Groq). The default configuration also enables a Telnet client for basic communication with the system.

### Step 6: Create the Hypercorn Configuration File

[Hypercorn](https://github.com/pgjones/hypercorn/) is an ASGI server that runs asynchronous web frameworks like Quart, which muGen is built upon. It can handle concurrent requests efficiently and supports modern web technologies, including HTTP/2 and WebSockets.

To configure Hypercorn, create a `hypercorn.toml` file:

```shell
~$ touch hypercorn.toml
```

Set a bind address to tell Hypercorn where to listen for incoming connections. Edit `hypercorn.toml` and add the following line:

```toml
bind = "127.0.0.1:8081"
```

This configuration specifies that Hypercorn will listen on your local machine (localhost) at port 8081. You can change the address or port later to meet your deployment requirements.

### Step 7: Initialize the Python Environment

muGen uses [Poetry](https://python-poetry.org/) for dependency management. Poetry simplifies the process of installing and managing Python libraries. Make sure Poetry is installed, then run the following commands to set up your environment:

```shell
~$ poetry install  # Install dependencies defined in pyproject.toml

~$ poetry shell    # Activate a virtual environment for your project
```

### Step 8: Run the Application

Now, you can run your muGen application using Hypercorn:

```shell
~$ hypercorn -c hypercorn.toml quartman:mugen
```

This command tells Hypercorn to use the configuration file `hypercorn.toml` and run the `mugen` app defined in the `quartman` module.

### Step 9: Communicate with Your Application

The Telnet client is enabled by default, allowing you to interact with your application. Connect to it on port 8888:

```shell
~$ telnet localhost 8888
```

You should see output similar to:

```text
Trying 127.0.0.1...
Connected to localhost.
Escape character is '^]'.
~ user:
```

At the `~ user:` prompt, type messages to send to the system. Responses from muGen will be prefixed with `~ assistant:`.

## Next Steps

With your application directory set up, you can start [developing extensions for muGen](extensions.md) to add custom functionality, integrate external services, or build new features.