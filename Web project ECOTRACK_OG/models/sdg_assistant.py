from transformers import AutoTokenizer, AutoModelForCausalLM

model_name = "tiiuae/falcon-7b-instruct"

tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name)


def ask_sdg(prompt):
    input_ids = tokenizer(prompt, return_tensors="pt").input_ids
    output = model.generate(input_ids, max_length=256)
    return tokenizer.decode(output[0], skip_special_tokens=True)
