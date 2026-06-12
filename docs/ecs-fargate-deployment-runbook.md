# ECS Fargate Deployment Runbook

Status: Manual first-deployment runbook plus automated push-to-main deployment
Audience: Operators deploying the muGen API to AWS ECS Fargate

## Scope

This runbook describes a manual first deployment of the muGen API container to
AWS ECS Fargate behind an Application Load Balancer, plus the GitHub Actions
automation used for later upstream releases. DNS provider instructions are kept
generic.

Do not copy, mount, upload, or bake local `mugen.toml` into the image or ECS
task. Production runtime values must come from ECS environment variables and AWS
Secrets Manager.

## Architecture

```text
DNS provider
  -> Application Load Balancer in public subnets
  -> ECS Fargate tasks in private subnets on port 8000
  -> RDS PostgreSQL in private subnets on port 5432
```

Key AWS terms:

- Region: the AWS geography, such as `us-east-1`.
- Availability Zone: an isolated data-center zone inside a region.
- VPC: the private network that contains subnets and routing.
- Public subnet: subnet whose route table sends internet-bound traffic to an
  Internet Gateway.
- Private subnet: subnet without a direct public inbound path.
- NAT Gateway: lets private-subnet resources make outbound internet requests.
- ALB: Application Load Balancer; public HTTPS entry point for the API.
- Target group: ALB backend pool and health-check configuration.
- ECS cluster: ECS scheduling boundary for services and tasks.
- Task definition: container runtime blueprint.
- ECS service: keeps one or more copies of a task running.

## Naming And Placeholders

The examples use these names. Replace placeholder values for your account and
environment.

```bash
export AWS_PROFILE=mugen-deployer
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=<aws-account-id>
export IMAGE_TAG=<main-git-sha-or-release-tag>
export IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/mugen-api:${IMAGE_TAG}"
```

Common resource names:

| Resource | Example |
| --- | --- |
| VPC | `mugen-api` |
| ECS cluster | `mugen-prod` |
| ECS service | `mugen-api` |
| ECR repository | `mugen-api` |
| CloudWatch log group | `/ecs/mugen-api` |
| Execution role | `mugenEcsExecutionRole` |
| Application task role | `mugenApiTaskRole` |
| ALB security group | `sg-mugen-alb` |
| ECS task security group | `sg-mugen-api` |
| RDS security group | `sg-mugen-db` |

Verify the active AWS CLI identity before running deployment commands:

```bash
aws sts get-caller-identity
aws configure list
```

The account, profile, and region must match the deployment target. If you do not
export `AWS_PROFILE` and `AWS_REGION`, pass `--profile` and `--region` to every
AWS CLI command.

## Production Release Source

Production ECS images must be built from `main` or from an immutable release tag
that points at a commit already on `main`. Treat `develop` as the integration
branch; do not build production ECS images from `develop`, feature branches, or
a dirty local worktree.

To deploy the current `main` commit:

```bash
git fetch origin --tags
git checkout main
git pull --ff-only origin main
test -z "$(git status --short)" || { git status --short; exit 1; }

export IMAGE_TAG="$(git rev-parse --short HEAD)"
export IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/mugen-api:${IMAGE_TAG}"
```

To deploy a release tag:

```bash
export RELEASE_TAG=v0.51.0

git fetch origin --tags
git checkout "$RELEASE_TAG"
git merge-base --is-ancestor HEAD origin/main
test -z "$(git status --short)" || { git status --short; exit 1; }

export IMAGE_TAG="$RELEASE_TAG"
export IMAGE_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/mugen-api:${IMAGE_TAG}"
```

Use a unique image tag for every release. Do not use `latest` in the production
task definition, because ECS rollbacks and audits need an immutable image
reference.

## Automated Production Deployment

After the one-time AWS resources exist, upstream muGen can deploy automatically
from `main` with `.github/workflows/deploy-ecs.yml`.

Creating a GitHub Release entry by itself does not deploy ECS. The active
deployment triggers are:

- a push to `main`,
- a manual `workflow_dispatch` run from GitHub Actions.

The workflow:

1. Runs on `push` to `main` and `workflow_dispatch`.
2. Uses the GitHub Environment named `production`.
3. Authenticates to AWS with GitHub OIDC, not long-lived AWS access keys.
4. Builds and pushes `mugen-api:${GITHUB_SHA}` to ECR.
5. Renders `.aws/ecs-task-definition.template.json`.
6. Registers a new ECS task definition revision.
7. Runs `python scripts/run_migration_tracks.py upgrade head` as a one-off
   Fargate task.
8. Runs `python -m mugen.core.plugin.acp.migration.reseed_manifest` as a
   one-off Fargate task.
9. Updates the ECS service only after migration and reseed containers exit `0`.
10. Waits for ECS service stability.
11. Smoke tests `ECS_HEALTHCHECK_URL`, which should point at `/health`.

The reseed command uses the same resolved deployment config as migrations:
`MUGEN_CONFIG_FILE`, generic config overlays, extension overlays,
`MUGEN_ENABLED_EXTENSIONS`, and Secrets Manager-injected env vars are all
honored. It re-applies idempotent ACP manifest data for currently enabled
extensions. That keeps route-visibility and resource permission seed data in
sync when an existing database enables a plugin after the plugin's historical
Alembic reseed migration has already run.

The upstream workflow deploys only the upstream/core muGen API service.
Downstream applications must configure their own AWS role, ECR repository, ECS
service, task template, plugin overlays, migration tracks, and smoke tests.

### GitHub Environment Variables

Create or update the `production` GitHub Environment:

```text
Repository -> Settings -> Environments -> production
```

Use these GitHub UI steps:

1. Open the upstream repository on GitHub.
2. Go to `Settings`.
3. Go to `Environments`.
4. Click `New environment` if `production` does not exist.
5. Name the environment exactly `production`.
6. Add required reviewers if production deploys should require manual approval.
7. Add deployment branch restrictions if desired. For the upstream workflow,
   allow `main`. If you plan to manually dispatch from release tags, allow the
   matching tag pattern too.
8. Add the values below under `Environment variables`.

Configure required reviewers or other environment protection rules in the
environment. The workflow YAML does not need to change when protection rules
change.

Set these environment variables. They are configuration values and secret ARN
references, not the runtime secret values themselves.

Use GitHub Environment variables for these values, not repository-level
variables, unless you intentionally change the workflow to read from repository
variables outside an environment. The job is scoped to `environment:
production`, so environment variables are the intended source.

| Variable | Example |
| --- | --- |
| `AWS_ROLE_TO_ASSUME` | `arn:aws:iam::<account-id>:role/mugenGithubDeployRole` |
| `AWS_REGION` | `us-east-1` |
| `AWS_ACCOUNT_ID` | `<account-id>` |
| `ECR_REPOSITORY` | `mugen-api` |
| `ECS_CLUSTER` | `mugen-prod` |
| `ECS_SERVICE` | Existing ECS service name, for example `mugen-api-service-6p5dx07a` |
| `ECS_CONTAINER_NAME` | `mugen-api` |
| `ECS_TASK_EXECUTION_ROLE_ARN` | `arn:aws:iam::<account-id>:role/mugenEcsExecutionRole` |
| `ECS_TASK_ROLE_ARN` | `arn:aws:iam::<account-id>:role/mugenApiTaskRole` |
| `ECS_TASK_SUBNETS` | `subnet-private-a,subnet-private-b` |
| `ECS_TASK_SECURITY_GROUPS` | `sg-mugen-api` |
| `ECS_ASSIGN_PUBLIC_IP` | `DISABLED` |
| `ECS_LOG_GROUP` | `/ecs/mugen-api` |
| `ECS_HEALTHCHECK_URL` | `https://api.example.com/health` |
| `CORS_ALLOWED_ORIGINS` | `https://app.example.com` |
| `DATABASE_URL_SECRET_ARN` | Secrets Manager ARN for `DATABASE_URL` |
| `SECRET_KEY_SECRET_ARN` | Secrets Manager ARN for `SECRET_KEY` |
| `ACP_ADMIN_USERNAME_SECRET_ARN` | Secrets Manager ARN for `ACP_ADMIN_USERNAME` |
| `ACP_ADMIN_LOGIN_EMAIL_SECRET_ARN` | Secrets Manager ARN for `ACP_ADMIN_LOGIN_EMAIL` |
| `ACP_ADMIN_PASSWORD_SECRET_ARN` | Secrets Manager ARN for `ACP_ADMIN_PASSWORD` |
| `ACP_ADMIN_PASSWORD_HASH_SECRET_ARN` | Secrets Manager ARN for `ACP_ADMIN_PASSWORD_HASH` |
| `ACP_SECRET_KEY_SECRET_ARN` | Secrets Manager ARN for `ACP_SECRET_KEY` |
| `ACP_MANAGED_SECRET_ENCRYPTION_KEY_SECRET_ARN` | Secrets Manager ARN for `ACP_MANAGED_SECRET_ENCRYPTION_KEY` |
| `ACP_REFRESH_TOKEN_PEPPER_SECRET_ARN` | Secrets Manager ARN for `ACP_REFRESH_TOKEN_PEPPER` |
| `ACP_JWT_CONFIG_JSON_SECRET_ARN` | Secrets Manager ARN for `ACP_JWT_CONFIG_JSON` |
| `MUGEN_CONFIG_OVERLAY_JSON_SECRET_ARN` | Secrets Manager ARN for `MUGEN_CONFIG_OVERLAY_JSON` |

`ECS_SERVICE` must be the existing service name inside `ECS_CLUSTER`. It is not
the task-definition family, container name, or desired friendly name unless the
actual ECS service uses that exact name.

Find the service name with:

```bash
aws ecs list-services \
  --cluster mugen-prod

aws ecs describe-services \
  --cluster mugen-prod \
  --services <service-name>
```

Do not store `DATABASE_URL`, `SECRET_KEY`, ACP keys, JWT private keys, or
provider API keys directly in GitHub variables or secrets for this workflow.
Store those values in AWS Secrets Manager and place only the ARN references in
the GitHub Environment variables.

### GitHub OIDC Role

Create one deploy role that trusts GitHub's OIDC provider and is limited to the
repository and environment that may deploy production. Example trust policy for
upstream muGen:

First create or verify the GitHub OIDC provider:

1. Open AWS Console.
2. Go to `IAM`.
3. Go to `Identity providers`.
4. If `token.actions.githubusercontent.com` already exists, reuse it.
5. If it does not exist, choose `Add provider`.
6. Provider type: `OpenID Connect`.
7. Provider URL: `https://token.actions.githubusercontent.com`.
8. Audience: `sts.amazonaws.com`.
9. Add the provider.

Then create the deploy role:

1. Go to `IAM -> Roles`.
2. Choose `Create role`.
3. Trusted entity type: `Web identity`.
4. Identity provider: `token.actions.githubusercontent.com`.
5. Audience: `sts.amazonaws.com`.
6. Continue without attaching broad managed policies.
7. Role name: `mugenGithubDeployRole`.
8. Create the role.
9. Open the role and choose `Trust relationships -> Edit trust policy`.
10. Replace the generated trust policy with the policy below.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<account-id>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:vorsocom/mugen:environment:production"
        }
      }
    }
  ]
}
```

Downstream repositories must replace `vorsocom/mugen` and `production` with
their own repository and GitHub Environment.

The deploy role should be able to:

- push images to the configured ECR repository,
- register task definition revisions,
- run migration tasks,
- describe tasks and services,
- update only the target ECS service,
- pass only the configured ECS task execution role and application task role.

Use `iam:PassRole` with both a role resource restriction and the condition
`iam:PassedToService = ecs-tasks.amazonaws.com`.

Attach the deploy permissions as an inline policy:

1. Open `IAM -> Roles -> mugenGithubDeployRole`.
2. Go to `Permissions`.
3. Choose `Add permissions`.
4. Choose `Create inline policy`.
5. Choose the `JSON` editor.
6. Paste the policy shape below after replacing placeholders.
7. Name the policy `MugenEcsDeployPolicy`.
8. Create the policy.

Example deploy-role policy shape:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrAuth",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "PushImage",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:CompleteLayerUpload",
        "ecr:DescribeRepositories",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart"
      ],
      "Resource": "arn:aws:ecr:<region>:<account-id>:repository/mugen-api"
    },
    {
      "Sid": "RegisterTaskDefinitions",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeTaskDefinition",
        "ecs:RegisterTaskDefinition"
      ],
      "Resource": "*"
    },
    {
      "Sid": "RunAndInspectMigrationTasks",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeTasks",
        "ecs:RunTask"
      ],
      "Resource": "*"
    },
    {
      "Sid": "UpdateOnlyMugenService",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeServices",
        "ecs:UpdateService"
      ],
      "Resource": "arn:aws:ecs:<region>:<account-id>:service/mugen-prod/mugen-api"
    },
    {
      "Sid": "PassOnlyMugenTaskRoles",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::<account-id>:role/mugenEcsExecutionRole",
        "arn:aws:iam::<account-id>:role/mugenApiTaskRole"
      ],
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "ecs-tasks.amazonaws.com"
        }
      }
    }
  ]
}
```

If your organization uses AWS IAM permissions boundaries, apply a boundary that
does not exceed the same ECR, ECS, and `iam:PassRole` scope. Downstream apps
should replace repository, cluster, service, and role resources with their own
names instead of sharing the upstream production deploy role.

The deploy role normally does not need `secretsmanager:GetSecretValue` for app
runtime secrets. ECS reads task-definition secrets through
`mugenEcsExecutionRole` when it starts the task. Grant Secrets Manager access to
the execution role for the exact secret ARN patterns used by the task
definition.

### Task Template And Reusable Action

The upstream task template is `.aws/ecs-task-definition.template.json`. It
contains only upstream/core muGen runtime fields. The workflow passes placeholder
values through environment variables whose names start with `TASKDEF_`; for
example, `TASKDEF_DATABASE_URL_SECRET_ARN` fills
`{{DATABASE_URL_SECRET_ARN}}`.

The reusable deployment mechanics live in `.github/actions/ecs-deploy/`. The
action assumes AWS credentials are already configured and accepts the ECR, ECS,
network, task template, migration command, ACP reseed command, and health-check
settings as inputs. It can be called locally by the upstream workflow or reused
by downstream repos pinned to a muGen release tag:

```yaml
- uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: ${{ vars.AWS_ROLE_TO_ASSUME }}
    aws-region: ${{ vars.AWS_REGION }}

- uses: vorsocom/mugen/.github/actions/ecs-deploy@v0.51.0
  env:
    TASKDEF_ACME_BILLING_CONFIG_JSON_SECRET_ARN: ${{ vars.ACME_BILLING_CONFIG_JSON_SECRET_ARN }}
  with:
    aws-region: ${{ vars.AWS_REGION }}
    aws-account-id: ${{ vars.AWS_ACCOUNT_ID }}
    ecr-repository: ${{ vars.ECR_REPOSITORY }}
    image-tag: ${{ github.sha }}
    docker-context: .
    dockerfile: Dockerfile
    ecs-cluster: ${{ vars.ECS_CLUSTER }}
    ecs-service: ${{ vars.ECS_SERVICE }}
    ecs-container-name: ${{ vars.ECS_CONTAINER_NAME }}
    task-template: .aws/ecs-task-definition.template.json
    task-execution-role-arn: ${{ vars.ECS_TASK_EXECUTION_ROLE_ARN }}
    task-role-arn: ${{ vars.ECS_TASK_ROLE_ARN }}
    task-subnets: ${{ vars.ECS_TASK_SUBNETS }}
    task-security-groups: ${{ vars.ECS_TASK_SECURITY_GROUPS }}
    reseed-command-json: '["python","-m","mugen.core.plugin.acp.migration.reseed_manifest"]'
    health-url: ${{ vars.ECS_HEALTHCHECK_URL }}
```

Downstream apps can instead copy the action and template if they need heavier
customization.

### Downstream Image And Overlay Example

A downstream app should add its code to the image, then declare runtime metadata
through environment and secret overlays:

```dockerfile
FROM <account-id>.dkr.ecr.<region>.amazonaws.com/mugen-api:<mugen-release-sha>

COPY plugins/acme_billing /app/plugins/acme_billing
RUN pip install --no-cache-dir /app/plugins/acme_billing
```

Downstream task templates typically extend the upstream template with:

```json
{
  "environment": [
    {
      "name": "MUGEN_ENABLED_EXTENSIONS",
      "value": "acme.billing"
    }
  ],
  "secrets": [
    {
      "name": "MUGEN_EXTENSIONS_JSON",
      "valueFrom": "arn:aws:secretsmanager:<region>:<account-id>:secret:acme/prod/MUGEN_EXTENSIONS_JSON"
    },
    {
      "name": "MUGEN_MIGRATION_TRACKS_JSON",
      "valueFrom": "arn:aws:secretsmanager:<region>:<account-id>:secret:acme/prod/MUGEN_MIGRATION_TRACKS_JSON"
    },
    {
      "name": "ACME_BILLING_CONFIG_JSON",
      "valueFrom": "arn:aws:secretsmanager:<region>:<account-id>:secret:acme/prod/ACME_BILLING_CONFIG_JSON"
    }
  ]
}
```

The plugin owns the shape and validation of `ACME_BILLING_CONFIG_JSON`. Core
muGen only validates the generic extension and migration overlay contracts.

## 1. Create Networking

Create a VPC with the console wizard:

```text
Resources: VPC and more
Name: mugen-api
IPv4 CIDR: 10.0.0.0/16
Availability Zones: 2
Public subnets: 2
Private subnets: 2
NAT gateways: Regional - new
VPC endpoints: S3 Gateway
DNS hostnames: enabled
DNS resolution: enabled
```

The wizard creates and attaches an Internet Gateway automatically when public
subnets are requested. Public subnet route tables should include:

```text
0.0.0.0/0 -> igw-...
```

Private subnet route tables should include:

```text
0.0.0.0/0 -> nat-...
```

Use the public subnets for the ALB. Use the private subnets for ECS tasks and
RDS PostgreSQL.

## 2. Create Security Groups

Leave the VPC default security group alone, but do not use it for ALB, ECS, or
RDS. Create dedicated security groups.

`sg-mugen-alb`:

```text
Inbound:
  TCP 443 from 0.0.0.0/0
  TCP 80 from 0.0.0.0/0, optional redirect only
Outbound:
  All traffic, or TCP 8000 to sg-mugen-api
```

`sg-mugen-api`:

```text
Inbound:
  TCP 8000 from sg-mugen-alb
Outbound:
  All traffic
```

`sg-mugen-db`:

```text
Inbound:
  TCP 5432 from sg-mugen-api
Outbound:
  All traffic
```

## 3. Create RDS PostgreSQL

Use plain RDS PostgreSQL for the first demo deployment. Aurora PostgreSQL is a
later scaling and high-availability choice, not required for the first ECS test.

Recommended demo settings:

```text
Engine: PostgreSQL
Template: Free tier, when available
Instance class: db.t4g.micro or db.t3.micro
Deployment: Single-AZ
Public access: No
VPC: mugen-api
Subnets: private subnets
Security group: sg-mugen-db
Database name: mugen
Credentials: Managed in AWS Secrets Manager
```

The application expects a SQLAlchemy URL:

```text
postgresql+psycopg://<db-user>:<db-password>@<rds-endpoint>:5432/mugen
```

If RDS manages the username and password as separate JSON fields, create a
separate Secrets Manager secret named like `mugen/api/prod/DATABASE_URL` whose
value is the complete SQLAlchemy URL.

## 4. Create Deployment IAM Principal

Use a dedicated deployer principal, not a broadly-scoped personal user. The
examples assume:

```text
IAM user: com.example.mugen.deployer
AWS CLI profile: mugen-deployer
```

The deployer needs enough permission to:

- create/read/push ECR repository images
- create/read ECS clusters, task definitions, tasks, and services
- create/read CloudWatch log groups and log streams
- read deployment secrets metadata and values when needed
- pass only the muGen ECS execution and application task roles to ECS tasks
- describe VPC, subnet, security group, and load balancer resources

The `iam:PassRole` permission should be scoped to the ECS task roles and
conditioned to `ecs-tasks.amazonaws.com`.

## 5. Create ECS Roles

Create both roles with:

```text
Trusted entity type: AWS service
Use case: Elastic Container Service Task
Trust principal: ecs-tasks.amazonaws.com
```

`mugenEcsExecutionRole` is used by ECS to start the task. Attach:

- `AmazonECSTaskExecutionRolePolicy`
- `secretsmanager:GetSecretValue` for `mugen/api/prod/*`
- `kms:Decrypt` if the secrets use a customer-managed KMS key

`mugenApiTaskRole` is used by the running application. Keep it minimal for the
deterministic demo gateway. Add service-specific permissions later, such as
Bedrock invoke, SES send, or S3 object access, only when those gateways are
selected.

## 6. Verify The ECS Service-Linked Role

Amazon ECS also needs an account-level service-linked role named
`AWSServiceRoleForECS`. This is different from the task execution role and the
application task role. ECS uses it to manage ECS-owned integrations with other
AWS services on behalf of the account.

Check whether it exists:

```bash
aws iam get-role --role-name AWSServiceRoleForECS
```

If that command returns `AccessDenied`, ask an AWS administrator to verify or
create the role. The deployer does not need broad IAM administration for normal
deployments, but someone must be able to perform this one-time account setup.

If it is missing, create it:

```bash
aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com
```

If the deployer principal cannot create service-linked roles, an AWS
administrator must run the command once or grant the deployer constrained
permission to create only the ECS service-linked role. A missing role can cause
`aws ecs run-task` to fail before the container starts:

```text
InvalidParameterException: Unable to assume the service linked role.
Please verify that the ECS service linked role exists.
```

## 7. Create Secrets

Create one Secrets Manager secret per runtime environment variable.

Required for the first production-like deployment:

```text
mugen/api/prod/DATABASE_URL
mugen/api/prod/SECRET_KEY
mugen/api/prod/ACP_ADMIN_USERNAME
mugen/api/prod/ACP_ADMIN_LOGIN_EMAIL
mugen/api/prod/ACP_ADMIN_PASSWORD
mugen/api/prod/ACP_ADMIN_PASSWORD_HASH
mugen/api/prod/ACP_SECRET_KEY
mugen/api/prod/ACP_MANAGED_SECRET_ENCRYPTION_KEY
mugen/api/prod/ACP_REFRESH_TOKEN_PEPPER
mugen/api/prod/ACP_JWT_CONFIG_JSON
mugen/api/prod/MUGEN_CONFIG_OVERLAY_JSON
```

Required non-secret task environment values include:

```text
ENVIRONMENT=production
APP_NAME=mugen-api
PORT=8000
LOG_LEVEL=INFO
CORS_ALLOWED_ORIGINS=https://app.example.com
MUGEN_CONFIG_FILE=conf/mugen.toml.sample
MUGEN_PLATFORMS=web
MUGEN_PHASE_B_CRITICAL_PLATFORMS=web
ACP_SEED_ACP=true
```

`conf/mugen.toml.sample` already enables the upstream web/admin baseline:
ACP, Web, Context Engine, Audit, Channel Orchestration, and Knowledge Pack. Set
`MUGEN_ENABLED_EXTENSIONS` only when enabling additional opt-in extensions, such
as downstream plugin tokens or `core.fw.agent_runtime` after configuring
`[mugen.agent_runtime]`.

The task definition examples below assume each secret resolves to the exact
environment variable value. For example, the `SECRET_KEY` secret value should be
the secret string itself, not `{"SECRET_KEY":"..."}`.

If you choose to store multiple key/value pairs in one JSON secret, reference
the JSON key in the ECS task definition value, for example:

```text
arn:aws:secretsmanager:<region>:<account-id>:secret:mugen/api/prod/app-abc123:SECRET_KEY::
```

Without the `:SECRET_KEY::` suffix, ECS injects the full JSON document into the
environment variable.

Generate a matching ACP admin password hash:

```bash
python - <<'PY'
from getpass import getpass
from werkzeug.security import generate_password_hash

password = getpass("ACP admin password: ")
confirm = getpass("Confirm password: ")
if password != confirm:
    raise SystemExit("Passwords do not match.")
print(generate_password_hash(password))
PY
```

Store the plaintext password in `ACP_ADMIN_PASSWORD` and the generated hash in
`ACP_ADMIN_PASSWORD_HASH`. In production, `ACP_ADMIN_PASSWORD_HASH` may be
omitted only when `ACP_SEED_ACP=false`.

Generate an Ed25519 private key for ACP JWT signing:

```bash
python - <<'PY'
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

key = ed25519.Ed25519PrivateKey.generate()
print(key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode())
PY
```

Store `ACP_JWT_CONFIG_JSON` as one JSON secret value:

```json
{
  "active_kid": "prod-ed25519-2026-06",
  "issuer": "mugen-api",
  "audience": "mugen-ui",
  "keys": [
    {
      "kid": "prod-ed25519-2026-06",
      "alg": "EdDSA",
      "pem": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
    }
  ]
}
```

Initial `MUGEN_CONFIG_OVERLAY_JSON` for a deterministic demo:

```json
{
  "mugen": {
    "modules": {
      "core": {
        "gateway": {
          "completion": "deterministic",
          "logging": "standard"
        }
      }
    }
  }
}
```

## 8. Build And Push Image

Before building, complete [Production Release Source](#production-release-source)
so `IMAGE_TAG` and `IMAGE_URI` point at the exact `main` commit or release tag
being deployed.

Create the ECR repository:

```bash
aws ecr describe-repositories --repository-names mugen-api \
  >/dev/null \
  || aws ecr create-repository --repository-name mugen-api
```

Log Docker in to ECR:

```bash
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin \
    "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
```

Build and push:

```bash
docker build -t "$IMAGE_URI" .
docker push "$IMAGE_URI"
```

If `docker buildx build --push` stalls at registry credential sharing, use the
plain build and push flow above.

Verify the image:

```bash
aws ecr describe-images \
  --repository-name mugen-api \
  --image-ids imageTag="$IMAGE_TAG"
```

## 9. Create ECS Cluster And Log Group

Create the cluster:

```bash
aws ecs describe-clusters \
  --clusters mugen-prod \
  --query 'clusters[?status==`ACTIVE`].clusterName' \
  --output text \
  | grep -q '^mugen-prod$' \
  || aws ecs create-cluster --cluster-name mugen-prod
```

Verify it is active:

```bash
aws ecs describe-clusters \
  --clusters mugen-prod \
  --query 'clusters[0].status'
```

Create the log group:

```bash
aws logs describe-log-groups \
  --log-group-name-prefix /ecs/mugen-api \
  --query 'logGroups[?logGroupName==`/ecs/mugen-api`]' \
  --output text \
  | grep -q /ecs/mugen-api \
  || aws logs create-log-group --log-group-name /ecs/mugen-api
```

## 10. Register Task Definition

Create a task definition JSON file outside the protected local runtime config.
Use a tagged image, not an untagged repository name.

```json
{
  "family": "mugen-api",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "executionRoleArn": "arn:aws:iam::<aws-account-id>:role/mugenEcsExecutionRole",
  "taskRoleArn": "arn:aws:iam::<aws-account-id>:role/mugenApiTaskRole",
  "containerDefinitions": [
    {
      "name": "mugen-api",
      "image": "<aws-account-id>.dkr.ecr.<region>.amazonaws.com/mugen-api:<image-tag>",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        { "name": "MUGEN_CONFIG_FILE", "value": "conf/mugen.toml.sample" },
        { "name": "ENVIRONMENT", "value": "production" },
        { "name": "APP_NAME", "value": "mugen-api" },
        { "name": "PORT", "value": "8000" },
        { "name": "LOG_LEVEL", "value": "INFO" },
        { "name": "CORS_ALLOWED_ORIGINS", "value": "https://app.example.com" },
        { "name": "MUGEN_PLATFORMS", "value": "web" },
        { "name": "MUGEN_PHASE_B_CRITICAL_PLATFORMS", "value": "web" },
        { "name": "ACP_SEED_ACP", "value": "true" }
      ],
      "secrets": [
        { "name": "DATABASE_URL", "valueFrom": "<secret-arn-for-DATABASE_URL>" },
        { "name": "SECRET_KEY", "valueFrom": "<secret-arn-for-SECRET_KEY>" },
        { "name": "ACP_ADMIN_USERNAME", "valueFrom": "<secret-arn-for-ACP_ADMIN_USERNAME>" },
        { "name": "ACP_ADMIN_LOGIN_EMAIL", "valueFrom": "<secret-arn-for-ACP_ADMIN_LOGIN_EMAIL>" },
        { "name": "ACP_ADMIN_PASSWORD", "valueFrom": "<secret-arn-for-ACP_ADMIN_PASSWORD>" },
        { "name": "ACP_ADMIN_PASSWORD_HASH", "valueFrom": "<secret-arn-for-ACP_ADMIN_PASSWORD_HASH>" },
        { "name": "ACP_SECRET_KEY", "valueFrom": "<secret-arn-for-ACP_SECRET_KEY>" },
        { "name": "ACP_MANAGED_SECRET_ENCRYPTION_KEY", "valueFrom": "<secret-arn-for-ACP_MANAGED_SECRET_ENCRYPTION_KEY>" },
        { "name": "ACP_REFRESH_TOKEN_PEPPER", "valueFrom": "<secret-arn-for-ACP_REFRESH_TOKEN_PEPPER>" },
        { "name": "ACP_JWT_CONFIG_JSON", "valueFrom": "<secret-arn-for-ACP_JWT_CONFIG_JSON>" },
        { "name": "MUGEN_CONFIG_OVERLAY_JSON", "valueFrom": "<secret-arn-for-MUGEN_CONFIG_OVERLAY_JSON>" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/mugen-api",
          "awslogs-region": "<region>",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

Validate JSON and register it:

```bash
python -m json.tool task-definition.json >/tmp/mugen-api-task-definition.json

aws ecs register-task-definition \
  --cli-input-json file:///tmp/mugen-api-task-definition.json
```

The `file://` prefix is required. Without it, the AWS CLI treats the path itself
as a JSON string and reports invalid JSON.

Capture the latest task definition ARN:

```bash
export TASK_DEF="$(aws ecs describe-task-definition \
  --task-definition mugen-api \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)"
```

## 11. Run Database Migrations

Use the same image and task definition for migrations. Override only the command.

Set network IDs:

```bash
export PRIVATE_SUBNET_1=<private-subnet-id-a>
export PRIVATE_SUBNET_2=<private-subnet-id-b>
export ECS_TASK_SG=<sg-mugen-api-id>
```

Run the migration task:

```bash
export MIGRATION_TASK_ARN="$(aws ecs run-task \
  --cluster mugen-prod \
  --launch-type FARGATE \
  --task-definition "$TASK_DEF" \
  --network-configuration "awsvpcConfiguration={subnets=[$PRIVATE_SUBNET_1,$PRIVATE_SUBNET_2],securityGroups=[$ECS_TASK_SG],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"mugen-api","command":["python","scripts/run_migration_tracks.py","upgrade","head"]}]}' \
  --query 'tasks[0].taskArn' \
  --output text)"
```

If the command is wrapped by a shell, make sure `"python"` is not split across a
line inside the JSON string.

Inspect the task:

```bash
aws ecs describe-tasks \
  --cluster mugen-prod \
  --tasks "$MIGRATION_TASK_ARN" \
  --query 'tasks[0].{lastStatus:lastStatus,stoppedReason:stoppedReason,containers:containers[*].{name:name,lastStatus:lastStatus,exitCode:exitCode,reason:reason}}'
```

Check logs:

```bash
aws logs tail /ecs/mugen-api --since 30m
```

Do not create or update the long-running service until the migration task exits
with code `0`.

## 12. Create ALB, Target Group, And Listener

Create an Application Load Balancer:

```text
Scheme: internet-facing
Subnets: public subnets
Security group: sg-mugen-alb
```

Create a target group:

```text
Target type: IP
Protocol: HTTP
Port: 8000
Health check protocol: HTTP
Health check port: Traffic port
Health check path: /health
Success code: 200
Protocol version: HTTP1
```

The public ALB listener may use HTTPS on port `443`, but the target group for
muGen must use HTTP to the container. Do not create an HTTPS target group for
the API container unless the container itself is serving TLS.

Create an HTTPS listener:

```text
Port: 443
Certificate: public certificate for the API hostname
Action: forward to the target group
```

Optionally create an HTTP listener that redirects port `80` to HTTPS `443`.
TLS should terminate at the ALB; do not configure `TLS_CERT_FILE` or
`TLS_KEY_FILE` in ECS.

## 13. Create ECS Service

After migrations pass, create the service:

```bash
aws ecs create-service \
  --cluster mugen-prod \
  --service-name mugen-api \
  --task-definition "$TASK_DEF" \
  --desired-count 1 \
  --launch-type FARGATE \
  --health-check-grace-period-seconds 900 \
  --network-configuration "awsvpcConfiguration={subnets=[$PRIVATE_SUBNET_1,$PRIVATE_SUBNET_2],securityGroups=[$ECS_TASK_SG],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=<target-group-arn>,containerName=mugen-api,containerPort=8000"
```

For a high-availability production deployment, use `--desired-count 2` or more.
For a first demo, `1` is acceptable.

The health check grace period gives the task time to complete application
bootstrap before ECS replaces it because the ALB target is not healthy yet.
Reduce it later only after measured startup times are consistently shorter.

Wait for stability:

```bash
aws ecs wait services-stable \
  --cluster mugen-prod \
  --services mugen-api
```

Check target health:

```bash
aws elbv2 describe-target-health \
  --target-group-arn <target-group-arn>
```

## 14. Configure DNS

In your DNS provider, create a record for the API hostname that points to the
ALB DNS name.

Typical choices:

```text
api.example.com CNAME <alb-dns-name>
```

or provider-specific alias/ANAME records when available.

Smoke test:

```bash
curl https://api.example.com/health
```

Expected response:

```json
{"status":"ok"}
```

Configure the UI to call:

```text
https://api.example.com/api
```

`CORS_ALLOWED_ORIGINS` must include the UI origin, for example:

```text
https://app.example.com
```

## 15. Debugging

Use these commands in order:

```bash
aws ecs describe-services --cluster mugen-prod --services mugen-api
aws ecs list-tasks --cluster mugen-prod --service-name mugen-api
aws ecs describe-tasks --cluster mugen-prod --tasks <task-arn>
aws logs tail /ecs/mugen-api --since 30m
aws elbv2 describe-target-health --target-group-arn <target-group-arn>
```

Common failures:

```text
CannotPullContainerError
  Image tag missing, task execution role issue, ECR access issue, or no private
  subnet path to ECR through NAT or VPC endpoints.

ResourceInitializationError
  Execution role cannot read Secrets Manager, cannot decrypt the secret KMS key,
  or the secret ARN is wrong.

Database connection timeout
  RDS security group must allow TCP 5432 from sg-mugen-api. The task must run in
  subnets that can reach the RDS subnet group.

Production validation failure
  Missing secret, placeholder secret, invalid JWT JSON, wildcard CORS, or
  missing selected gateway credential.

Target unhealthy
  Wrong security group, wrong container port, app crash, or `/health`
  unreachable from the ALB target group.

HTTPS target group pointed at HTTP container
  The ALB listener can be HTTPS, but the target group should be HTTP on port
  `8000`. If `describe-target-groups` shows `Protocol=HTTPS` or
  `HealthCheckProtocol=HTTPS`, the ALB is attempting a TLS health check against
  a plain HTTP Hypercorn listener and targets will remain unhealthy.

Task starts Hypercorn and then stops during bootstrap
  If logs show `Running on http://0.0.0.0:8000`, `Bootstrap phase_b starting`,
  and later `Bootstrap phase_b completed ... status=stopped`, ECS may be
  stopping the task before bootstrap finishes because ALB health checks have not
  passed. Set or increase the ECS service health check grace period, then
  inspect ALB target health and service events.
```

## 16. Release Update Flow

For normal upstream releases, merge the release to `main`. The
`deploy-ecs.yml` workflow builds the immutable image, runs migrations, re-applies
the ACP seed manifest, updates the ECS service, waits for service stability, and
smoke tests `/health`.

Use the manual flow when bootstrapping the first deployment, recovering from a
partially configured GitHub Environment, or intentionally bypassing automation:

1. Merge or promote the release to `main`, or create a release tag from `main`.
2. Complete [Production Release Source](#production-release-source) and confirm
   the worktree is clean.
3. Build and push a new immutable ECR image tag.
4. Register a new task definition revision with the new image tag.
5. Run the migration one-off task using that revision.
6. If migrations exit `0`, run the ACP manifest reseed one-off task using that
   same revision:

   ```bash
   python -m mugen.core.plugin.acp.migration.reseed_manifest
   ```

7. If the reseed exits `0`, update the ECS service to the new revision.
8. Wait for service stability.
9. Smoke test `/health` and at least one authenticated API/UI workflow.

After enabling an ACP-backed extension, log out and log back in before checking
UI route visibility. Session roles are minted at login/refresh time; for
example, Knowledge Packs appears only when the session includes
`com.vorsocomputing.mugen.knowledge_pack:configurator`.

Rollback is an ECS service update to a known-good task definition revision:

```bash
aws ecs update-service \
  --cluster mugen-prod \
  --service mugen-api \
  --task-definition <previous-task-definition-arn>

aws ecs wait services-stable \
  --cluster mugen-prod \
  --services mugen-api
```

Rollbacks do not automatically reverse database migrations. Keep migrations
backward-compatible whenever possible.
