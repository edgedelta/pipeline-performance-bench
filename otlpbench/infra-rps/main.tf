terraform {
  required_providers {
    aws   = { source = "hashicorp/aws", version = "~> 5.0" }
    tls   = { source = "hashicorp/tls", version = "~> 4.0" }
    http  = { source = "hashicorp/http", version = "~> 3.0" }
    local = { source = "hashicorp/local", version = "~> 2.0" }
  }
}
provider "aws" { region = "us-west-2" }
data "http" "ip" { url = "https://checkip.amazonaws.com" }
data "aws_vpc" "default" { default = true }
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}
resource "tls_private_key" "ssh" {
  algorithm = "RSA"
  rsa_bits  = 4096
}
resource "local_file" "key" {
  content         = tls_private_key.ssh.private_key_pem
  filename        = "otlp-key.pem"
  file_permission = "0600"
}
resource "aws_key_pair" "ssh" {
  key_name_prefix = "otlp-preview-"
  public_key      = tls_private_key.ssh.public_key_openssh
}
resource "aws_security_group" "bench" {
  name_prefix = "otlp-preview-"
  vpc_id      = data.aws_vpc.default.id
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["${trimspace(data.http.ip.response_body)}/32"]
  }
  ingress {
    from_port = 4317
    to_port   = 4317
    protocol  = "tcp"
    self      = true
  }
  ingress {
    from_port = 14317
    to_port   = 14318
    protocol  = "tcp"
    self      = true
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
variable "instance_type" {
  type    = string
  default = "c8i.8xlarge"
}
resource "aws_instance" "bench" {
  for_each                    = toset(["load", "agent", "sink"])
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  key_name                    = aws_key_pair.ssh.key_name
  vpc_security_group_ids      = [aws_security_group.bench.id]
  subnet_id                   = tolist(data.aws_subnets.default.ids)[0]
  associate_public_ip_address = true
  root_block_device {
    volume_size           = 30
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }
  tags = { Name = "otlp-rps-${each.key}" }
}
output "hosts" { value = { for role, instance in aws_instance.bench : role => { public = instance.public_ip, private = instance.private_ip } } }
