# Temporary ECS Fargate Placeholder Service Runbook

Status: One-time bootstrap runbook for downstream muGen API deployments
Audience: Operators creating AWS resources before a downstream application's
first deployment

## Purpose

Some downstream deployment pipelines update an existing Amazon ECS service
rather than create one. Use this runbook to create that service, its target
group, and its Application Load Balancer (ALB) routing before the first real
application task-definition revision exists.

The temporary task runs `nginx:latest` and returns
`Awaiting initial deployment` over HTTP. The first downstream deployment
replaces the placeholder task definition on the same ECS service. Do not use
the nginx task as the application deployment or leave it serving production
traffic longer than necessary; `latest` is intentionally acceptable only for
this short-lived bootstrap task.

This runbook assumes the VPC, public ALB subnets, private ECS task subnets, ECS
cluster, ALB, listener, security groups, and ECS task execution role either
exist or are being created as part of the same environment setup. See the
[full ECS Fargate deployment runbook](ecs-fargate-deployment-runbook.md) for
the surrounding infrastructure.

## Port Contract

Port `8000` is the standard muGen API container port. Use it consistently for
the placeholder and the downstream application:

| Layer | Required setting |
| --- | --- |
| Placeholder nginx | `listen 8000` |
| Task-definition port mapping | `containerPort: 8000`, `hostPort: 8000` |
| ECS service load-balancer mapping | `containerPort=8000` |
| Target group | HTTP port `8000` |
| ALB health check | HTTP on traffic port `8000` |
| ECS task security group | TCP `8000` inbound from the ALB security group |
| Downstream application | Listen on `0.0.0.0:8000` |

The ALB listener can accept HTTP `80` or HTTPS `443`; that public listener port
does not alter the backend port contract. If a downstream application
explicitly requires another container port, change every row in this table
together. A partial port change leaves targets unhealthy or traffic
unreachable.

## Preserve Downstream Identifiers

Choose the identifiers expected by the downstream pipeline before creating
anything:

- ECS cluster name
- ECS service name
- task-definition family
- application container name
- CloudWatch log group
- VPC and private subnet IDs
- ALB listener ARN and listener-rule priority
- ALB and ECS task security-group IDs

The placeholder container name must equal the downstream application's
container name. ECS stores that name and port in the service's load-balancer
mapping, so a later task definition with a different container name cannot be
deployed to the service until the mapping is changed.

All examples use angle-bracket placeholders. Replace every placeholder before
running a command. Keep the resources in the same AWS account, Region, and VPC.

## 1. Configure Network Access

Configure the security groups with these minimum inbound rules:

```text
ALB security group:
  TCP 443 from the intended client CIDRs
  TCP 80 from the intended client CIDRs only when HTTP or HTTP-to-HTTPS redirect is used

ECS task security group:
  TCP 8000 from the ALB security group
```

Do not expose task port `8000` directly to the internet. Reference the ALB
security group as the source of the ECS task rule. The ECS task security group
also needs outbound access sufficient to pull `nginx:latest` and send logs, by
way of a NAT gateway or the appropriate VPC endpoints.

## 2. Create The IP Target Group And ALB Route

Create the target group in the task VPC:

```bash
aws elbv2 create-target-group \
  --name '<target-group-name>' \
  --protocol HTTP \
  --port 8000 \
  --target-type ip \
  --vpc-id '<vpc-id>' \
  --health-check-enabled \
  --health-check-protocol HTTP \
  --health-check-port traffic-port \
  --health-check-path / \
  --matcher HttpCode=200
```

`awsvpc` tasks have their own elastic network interfaces, so the target type
must be `ip`, not `instance`. Do not manually register a target: ECS registers
and deregisters each task IP when the service starts or replaces tasks.

Add a rule to the existing ALB listener. This host-header example keeps the
route generic; use the condition expected by the downstream application:

```bash
aws elbv2 create-rule \
  --listener-arn '<alb-listener-arn>' \
  --priority '<unused-listener-rule-priority>' \
  --conditions 'Field=host-header,Values=<api-hostname>' \
  --actions 'Type=forward,TargetGroupArn=<target-group-arn>'
```

For a dedicated listener, forwarding to this target group can instead be the
default action. TLS normally terminates at the ALB; traffic from the ALB to the
target group remains HTTP on port `8000`.

## 3. Create The CloudWatch Log Group

Create the log group if it does not already exist, and set an environment-
appropriate retention period:

```bash
aws logs create-log-group \
  --log-group-name '<cloudwatch-log-group>'

aws logs put-retention-policy \
  --log-group-name '<cloudwatch-log-group>' \
  --retention-in-days 30
```

The ECS task execution role must allow the actions needed by the `awslogs`
driver, including `logs:CreateLogStream` and `logs:PutLogEvents`, for this log
group.

## 4. Register The Placeholder Task Definition

Save the following as `placeholder-task-definition.json`. It uses Fargate,
`awsvpc` networking, the generic application container name required by the
future deployment, nginx on port `8000`, a container health check, and
CloudWatch logging.

```json
{
  "family": "<application-task-definition-family>",
  "networkMode": "awsvpc",
  "requiresCompatibilities": [
    "FARGATE"
  ],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "<ecs-task-execution-role-arn>",
  "containerDefinitions": [
    {
      "name": "<application-container-name>",
      "image": "nginx:latest",
      "essential": true,
      "entryPoint": [
        "/bin/sh",
        "-c"
      ],
      "command": [
        "printf '%s\\n' 'server { listen 8000; default_type text/plain; location / { return 200 \"Awaiting initial deployment\\n\"; } }' > /etc/nginx/conf.d/default.conf && nginx -t && exec nginx -g 'daemon off;'"
      ],
      "portMappings": [
        {
          "name": "<application-container-name>-8000-tcp",
          "containerPort": 8000,
          "hostPort": 8000,
          "protocol": "tcp",
          "appProtocol": "http"
        }
      ],
      "healthCheck": {
        "command": [
          "CMD-SHELL",
          "nginx -t || exit 1"
        ],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 10
      },
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "<cloudwatch-log-group>",
          "awslogs-region": "<aws-region>",
          "awslogs-stream-prefix": "ecs-placeholder"
        }
      }
    }
  ]
}
```

Validate and register the task definition:

```bash
python -m json.tool placeholder-task-definition.json >/dev/null

aws ecs register-task-definition \
  --cli-input-json file://placeholder-task-definition.json
```

Record the returned task-definition ARN or the resulting family and revision.
Do not add application secrets, database access, or an application task role to
this placeholder unless another bootstrap requirement explicitly needs them.

## 5. Create The Rolling ECS Service

Create one Fargate task in the private subnets and attach it to the target
group. The `ECS` controller with `ROLLING` strategy performs rolling
deployments. The circuit breaker fails a deployment that cannot reach steady
state and rolls it back to the last completed deployment.

```bash
aws ecs create-service \
  --cluster '<ecs-cluster-name>' \
  --service-name '<ecs-service-name>' \
  --task-definition '<application-task-definition-family>:<placeholder-revision>' \
  --desired-count 1 \
  --launch-type FARGATE \
  --platform-version LATEST \
  --deployment-controller 'type=ECS' \
  --deployment-configuration 'strategy=ROLLING,minimumHealthyPercent=100,maximumPercent=200,deploymentCircuitBreaker={enable=true,rollback=true}' \
  --network-configuration 'awsvpcConfiguration={subnets=[<private-subnet-id-a>,<private-subnet-id-b>],securityGroups=[<ecs-task-security-group-id>],assignPublicIp=DISABLED}' \
  --load-balancers 'targetGroupArn=<target-group-arn>,containerName=<application-container-name>,containerPort=8000' \
  --health-check-grace-period-seconds 60 \
  --enable-ecs-managed-tags
```

The `minimumHealthyPercent=100` and `maximumPercent=200` settings allow ECS to
start a replacement before stopping the single healthy placeholder task,
provided the account has enough Fargate capacity. The service load-balancer
mapping, task-definition mapping, target group, security-group rule, and nginx
listener all use port `8000`.

## 6. Verify The Placeholder

Wait until ECS reports the service as stable:

```bash
aws ecs wait services-stable \
  --cluster '<ecs-cluster-name>' \
  --services '<ecs-service-name>'

aws ecs describe-services \
  --cluster '<ecs-cluster-name>' \
  --services '<ecs-service-name>' \
  --query 'services[0].{status:status,running:runningCount,pending:pendingCount,taskDefinition:taskDefinition,deployments:deployments[*].rolloutState,events:events[0:5].message}'
```

Confirm that the target is healthy and that requests reach nginx:

```bash
aws elbv2 describe-target-health \
  --target-group-arn '<target-group-arn>'

curl --fail --show-error 'https://<api-hostname>/'
```

The response should be `Awaiting initial deployment`. If the task or target is
unhealthy, inspect the recent ECS service events and CloudWatch logs before
handing the service to the downstream pipeline:

```bash
aws logs tail '<cloudwatch-log-group>' --since 30m
```

## 7. Hand Off To The First Application Deployment

Before starting the downstream pipeline, verify that its deployment variables
refer to the exact cluster, service, container, target group, and Region created
above. Its task definition must:

- use the same application container name;
- use `awsvpc` networking and Fargate compatibility;
- make the application listen on `0.0.0.0:8000`;
- map container and host port `8000`;
- retain CloudWatch logging; and
- serve the configured ALB health-check path on port `8000`.

The pipeline should register the first real application task-definition
revision and update the existing service, for example:

```bash
aws ecs update-service \
  --cluster '<ecs-cluster-name>' \
  --service '<ecs-service-name>' \
  --task-definition '<application-task-definition-family>:<application-revision>'
```

ECS then performs a rolling deployment. It registers the new application task
in the same target group and removes the nginx task only after the application
becomes healthy. Circuit-breaker rollback preserves the last completed
deployment if the first application revision fails to stabilize.

After the application deployment succeeds, confirm that the service's primary
task definition is the application revision, the target is healthy, and the
application health endpoint responds. No separate placeholder service remains
to delete: the placeholder was a task-definition revision of the permanent ECS
service.

## References

- [Amazon ECS service load balancing](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-load-balancing.html)
- [Amazon ECS deployment failure detection and circuit breaker](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html)
- [Amazon ECS task-definition differences for Fargate](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-tasks-services.html)
- [Send Amazon ECS logs to CloudWatch](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/using_awslogs.html)
