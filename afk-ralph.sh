
set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <iterations>"
  exit 1
fi

for ((i=1; i<=$1; i++)); do
  result=$(claude --permission-mode acceptEdits -p "Study  @docs/AGENT_DESIGN_REFERENCE.md, @README.md and langchain-docs (using MCP) using subagents.       
  Criticize the plan, find gaps, and improve it. 
  If nothing is wrong, do not propose unnecessary alternatives. 
  If there is a gap, propose a solution.
  ONLY WORK ON A SINGLE ISSUE AT A TIME. 
  Record your progress in @progress.txt. 
  Commit your changes to the conversation-agent branch.\
  If the PLAN is complete, output <promise>COMPLETE</promise>.")

  echo "$result"

  if [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then
    echo "Plan complete after $i iterations."
    exit 0
  fi
done