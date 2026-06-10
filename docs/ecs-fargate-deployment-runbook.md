# ECS Fargate Deployment Runbook

Status: Manual first-deployment runbook; CI/CD automation deferred
Audience: Operators deploying the muGen API to AWS ECS Fargate

## Scope

This runbook describes a manual first deployment of the muGen API container to
AWS ECS Fargate behind an Application Load Balancer. It intentionally keeps DNS
provider instructions generic and assumes pipeline automation is a follow-up.

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
export IMAGE_TAG=<git-sha-or-release-tag>
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
MUGEN_ENABLED_EXTENSIONS=core.fw.channel_orchestration,core.fw.audit
ACP_SEED_ACP=true
```

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
        { "name": "MUGEN_ENABLED_EXTENSIONS", "value": "core.fw.channel_orchestration,core.fw.audit" },
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

For later releases:

1. Build and push a new ECR image tag.
2. Register a new task definition revision with the new image tag.
3. Run the migration one-off task using that revision.
4. If migrations exit `0`, update the ECS service to the new revision.
5. Wait for service stability.
6. Smoke test `/health` and at least one authenticated API/UI workflow.
