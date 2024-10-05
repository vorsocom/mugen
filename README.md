<p align="center">
    <img src="assets/images/mugen-logotype.png" width="401">
</p>

# muGen - The GenAI Microframework

muGen (pronounced mew-jen) is a [fair-code](https://faircode.io) Python microframework for prototyping and deploying multimodal Generative AI applications. The aim is to have a simple, lean, extensible code base that allows developers to mix and match technologies and vendors providing, among other things, LLMs, vector storage, and communication platforms, to get from zero to deployment in as little time as possible. Continue reading for an overview of the framework, or skip ahead to [start building](#getting-started)

1. [Architecture](#architecture)
2. [Getting Started](#getting-started)
3. [License](#license)
4. [Enterprise Services](#enterprise-services)

## Architecture

There are five layers in a muGen app. They go from high-level platform UIs, to low-level core modules in the framework. Except for situations where a target platform uses a pull API, or where extensions implement API endpoints, the code base for the entire app can be kept fairly [clean](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html). This means that dependencies always point towards lower layers, increasing flexibility and testability.

<p align="center">
    <img src="assets/images/mugen-architecture.png" width="501">
</p>

### Platforms

The platform layer includes communication platforms through which users interact with your application. This could be anything from instant messaging platforms such as Matrix and WhatsApp (currently supported by muGen core), to your own web applications. More platforms will be added as the framework matures. It is possible to serve multiple platforms concurrently from a single muGen instance. It is left to the developer to decide if this would be desirable in their unique use case.

### API

muGen, at its core, is a [Quart](https://palletsprojects.com/projects/quart) application and, therefore, supports all the API building functionality of that framework. Blueprint registration of the core API is delayed until after extensions have been registered. This allows extensions to add their own endpoints to the core API, or implment custom API routes altogether.

### Extensions

muGen supports seven types of extensions which can all be platform agnostic or specific, each of which are activated at different stages of the message lifecycle. These types are:

1. **Framework (FW)** extensions: that work outside the message lifecycle to add functionality, such as API endpoints, to the core framework. They are registered and initialised during application startup.

2. **Inter-process Communication (IPC)** extensions: that handle incoming requests from the API to execute commands. They allow us to perform operations such as executing cron tasks and handling calls from push APIs.

3. **Message Hanlder (MH)** extensions: that are primarily used to handle non-text input to the system.

4. **Context (CTX)** extensions: that provide context to the LLM by injecting messages into conversation histories.

5. **Retrieval Augmented Generation (RAG)** extensions: that perform knowlegde retrieval from arbitrary sources and inject this knowledge into the LLM context.

6. **Response Pre-processor (RPP)** extensions: that intercept and modify LLM responses before they are shown to the user.

7. **Conversational Trigger (CT)** extensions: that look for cues in the final version of the LLM response and carry out operations if those cues are detected.

Extensions are developed against OOP style interfaces, never concrete implementations, and rely on dependency injection to get access to core modules.

### Clients

Clients provide platform specific functionality and can be built for push and pull APIs. Clients for push APIs rely on IPC extensions to handle incoming requests from the core API. The client modules used by the core are configurable using the TOML configuration file.

### Gateways and Services

Gateways and services lie at the core of the framework and provide platform agnostic functionality. The naming convention was adopted to differentiate between core implemented functionality (services) and functionality provided by external libraries/systems (gateways). The gateway and service modules used by the core are configurable using the TOML configuration file.

## Getting Started

```bash
## Clone the main branch.
~$ git clone -b main --single-branch git@github.com:vorsocom/mugen.git

## Switch to the repo directory.
~$ cd mugen

## Copy the hypercorn config sample to the root folder.
~$ cp conf/hypercorn.toml.sample hypercorn.toml

## Edit hypercorn.toml to set your preferred values.
~$ nano hypercorn.toml

## Copy the app config sample to the root folder
~$ cp conf/mugen.toml.sample mugen.toml

## Edit mugen.toml to set your preffered values.
# Note that you should configure at least at least
# one platform and one completion gateway.
~$ nano mugen.toml

## Install Python dependencies.
~$ poetry install

## Activate the Python environment.
~$ poetry shell

## Run the app.
~$ hypercorn -c hypercorn.toml quartman:mugen
```

## License

muGen is [fair-code](https://faircode.io) distributed under the [**Sustainable Use License**](LICENSE.md). Proprietary enterprise licenses are available on [**request**](mailto:license@vorsocomputing.com).

## Enterprise Services

You may [**get in touch**](mailto:brightideas@vorsocomputing.com) with [Vorsocom](https://vorsocomputing.com) for enterprise support in building applications using muGen. Leverage our intimate knowledge of the platform to help you achieve your goals in a timely manner.